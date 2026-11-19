"""Step 3: Dataset/DataLoader only. Raw files are read-only."""
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
import warnings

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Subset

DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / "data" / "raw"


def read_sequence(path):
    """Raw shape (1, T, 126) -> sequence shape (T, 126)."""
    path = Path(path)
    try:
        raw = np.load(path, allow_pickle=False)
        if raw.ndim != 3 or raw.shape[0] != 1 or raw.shape[1] == 0 or raw.shape[2] != 126:
            raise ValueError(f"expected (1, T>0, 126), got {raw.shape}")
        if raw.dtype.kind not in "fiu" or not np.isfinite(raw).all():
            raise ValueError("expected finite real numeric coordinates")
        with np.errstate(over="ignore", invalid="ignore"):
            sequence = raw[0].astype(np.float32)
        if not np.isfinite(sequence).all():
            raise ValueError("coordinates overflow float32")
        return sequence
    except (OSError, ValueError, TypeError, EOFError) as exc:
        raise ValueError(f"Invalid sample {path}: {exc}") from exc


def fit_length(sequence, length):
    """Shape (T, 126) -> (length, 126); zero-pad tail or keep first frames."""
    if not isinstance(length, int) or isinstance(length, bool) or length < 1:
        raise ValueError("sequence_length must be a positive integer")
    output = np.zeros((length, 126), dtype=np.float32)
    valid_length = min(len(sequence), length)
    output[:valid_length] = sequence[:valid_length]
    return output


@dataclass(frozen=True)
class Sample:
    path: Path
    label: int
    source_length: int
    sha256: str
    signer: str | None
    session_id: str | None


class VSLDataset(Dataset):
    def __init__(self, root=DEFAULT_DATA_ROOT, sequence_length=30):
        self.root = Path(root).resolve()
        fit_length(np.zeros((1, 126), np.float32), sequence_length)
        self.sequence_length = sequence_length
        if not self.root.is_dir():
            raise ValueError(f"Dataset directory does not exist: {self.root}")
        folders = sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith('.'))
        if not folders:
            raise ValueError(f"No label folders in {self.root}")
        self.class_to_idx = {p.name: i for i, p in enumerate(folders)}
        self.samples = []
        hashes = {}
        for folder in folders:
            paths = sorted(folder.glob("*.npy"))
            if not paths:
                raise ValueError(f"Label has no .npy samples: {folder}")
            for path in paths:
                sequence = read_sequence(path)
                # Validate every file before split; never silently skip bad data.
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                content_hash = hashlib.sha256(sequence.tobytes()).hexdigest()
                if content_hash in hashes:
                    raise ValueError(f"Duplicate sample content: {path} and {hashes[content_hash]}")
                hashes[content_hash] = path
                metadata = {}
                sidecar = path.with_suffix(".json")
                if sidecar.exists():
                    try:
                        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                        if not isinstance(metadata, dict) or metadata.get("label") != folder.name:
                            raise ValueError("metadata label does not match folder")
                    except (ValueError, OSError) as exc:
                        raise ValueError(f"Invalid metadata {sidecar}: {exc}") from exc
                self.samples.append(Sample(path, self.class_to_idx[folder.name], len(sequence),
                                           digest, metadata.get("signer"), metadata.get("session_id")))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        sample = self.samples[index]
        sequence = read_sequence(sample.path)  # Shape: (T, 126).
        fitted = fit_length(sequence, self.sequence_length)
        features = torch.from_numpy(fitted)  # Shape: (Sequence_length, 126), float32.
        label = torch.tensor(sample.label, dtype=torch.long)  # Shape: (), scalar class index.
        return features, label


def stratified_split(dataset, validation_ratio=0.2, seed=42):
    """Split whole files, not frames; sample-level pipeline smoke only."""
    if not 0 < validation_ratio < 1:
        raise ValueError("validation_ratio must be between 0 and 1")
    groups = defaultdict(list)
    for index, sample in enumerate(dataset.samples):
        groups[sample.label].append(index)
    if len(groups) < 2:
        raise ValueError("Need at least two classes for classification smoke test")
    rng = random.Random(seed)
    train_indices, val_indices = [], []
    for label in sorted(groups):
        indices = groups[label].copy()
        if len(indices) < 2:
            raise ValueError(f"Class {label} needs at least 2 samples for train/validation")
        rng.shuffle(indices)
        # At least one sample of every class in both subsets.
        n_val = max(1, min(len(indices) - 1, int(len(indices) * validation_ratio + 0.5)))
        val_indices.extend(indices[:n_val])
        train_indices.extend(indices[n_val:])
    return sorted(train_indices), sorted(val_indices)


def create_dataloaders(root=DEFAULT_DATA_ROOT, sequence_length=30, batch_size=4,
                       validation_ratio=0.2, seed=42):
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    dataset = VSLDataset(root, sequence_length)
    train_indices, val_indices = stratified_split(dataset, validation_ratio, seed)
    warnings.warn("Sample-level split for pipeline smoke only; not independent signer/session validation.",
                  UserWarning, stacklevel=2)
    generator = torch.Generator().manual_seed(seed)
    # DataLoader collates X: (Batch_size, Sequence_length, 126), y: (Batch_size,).
    train_loader = DataLoader(Subset(dataset, train_indices), batch_size=batch_size,
                              shuffle=True, generator=generator, num_workers=0, drop_last=False)
    val_loader = DataLoader(Subset(dataset, val_indices), batch_size=batch_size,
                            shuffle=False, num_workers=0, drop_last=False)
    return train_loader, val_loader, dataset


def split_manifest(dataset, train_indices, val_indices, seed, validation_ratio):
    """Persist membership/provenance for inspection; never write raw coordinates."""
    def entries(indices):
        return [dict(path=dataset.samples[i].path.relative_to(dataset.root).as_posix(),
                     label=dataset.samples[i].label, sha256=dataset.samples[i].sha256,
                     source_length=dataset.samples[i].source_length,
                     signer=dataset.samples[i].signer, session_id=dataset.samples[i].session_id)
                for i in indices]
    return dict(schema_version=1, split_mode="stratified_sample_smoke", seed=seed,
                validation_ratio=validation_ratio, sequence_length=dataset.sequence_length,
                class_to_idx=dataset.class_to_idx, train=entries(train_indices), validation=entries(val_indices),
                limitation="Not independent signer/session validation. Adding files may change the split.")
