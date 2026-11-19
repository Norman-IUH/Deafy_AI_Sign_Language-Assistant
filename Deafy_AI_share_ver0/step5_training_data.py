"""Step 5: reuse verified split membership and align lengths under shuffle."""
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset, Subset
from step3_dataset import VSLDataset


class WithLengths(Dataset):
    def __init__(self, dataset):
        self.dataset = dataset

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, index):
        x, y = self.dataset[index]  # Shapes: (T,126), ().
        length = min(self.dataset.samples[index].source_length, self.dataset.sequence_length)
        return x, y, torch.tensor(length, dtype=torch.long)  # length shape: ().


def verify_manifest(dataset, manifest):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        raise ValueError('Unsupported split manifest schema')
    if manifest.get('split_mode') != 'stratified_sample_smoke':
        raise ValueError('Unsupported split mode')
    if manifest.get('sequence_length') != dataset.sequence_length or manifest.get('class_to_idx') != dataset.class_to_idx:
        raise ValueError('Split sequence_length/class mapping differs from dataset')
    lookup = {s.path.relative_to(dataset.root).as_posix(): i for i, s in enumerate(dataset.samples)}
    seen, subsets = set(), []
    for subset in ('train', 'validation'):
        entries = manifest.get(subset)
        if not isinstance(entries, list) or not entries:
            raise ValueError(f'Missing/empty {subset} split')
        indices = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Invalid split entry')
            relative = entry.get('path')
            # Match canonical dataset-relative paths; never open paths supplied by manifest.
            if not isinstance(relative, str) or relative not in lookup:
                raise ValueError(f'Split path absent or not canonical: {relative}')
            if relative in seen:
                raise ValueError(f'Duplicate/overlapping split path: {relative}')
            index = lookup[relative]
            sample = dataset.samples[index]
            if not sample.path.resolve().is_relative_to(dataset.root):
                raise ValueError(f'Sample resolves outside data directory: {relative}')
            expected = dict(label=sample.label, sha256=sample.sha256, source_length=sample.source_length)
            for key, value in expected.items():
                if entry.get(key) != value:
                    raise ValueError(f'Split {key} mismatch: {relative}')
            for key in ('signer', 'session_id'):
                if key in entry and entry[key] != getattr(sample, key):
                    raise ValueError(f'Split {key} mismatch: {relative}')
            seen.add(relative)
            indices.append(index)
        if {dataset.samples[i].label for i in indices} != set(dataset.class_to_idx.values()):
            raise ValueError(f'{subset} split must include every class')
        subsets.append(indices)
    if seen != set(lookup):
        raise ValueError('Dataset files added/missing relative to manifest; regenerate a reviewed Step3 split')
    return subsets[0], subsets[1]


def collect_preprocessing(dataset):
    keys = ('feature_order', 'mirrored_before_inference', 'coordinates', 'duration_seconds')
    canonical = None
    for sample in dataset.samples:
        sidecar = sample.path.with_suffix('.json')
        if not sidecar.is_file():
            raise ValueError(f'Collection metadata required for training: {sidecar}')
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        if any(key not in metadata for key in keys):
            raise ValueError(f'Missing preprocessing metadata: {sidecar}')
        current = {key: metadata[key] for key in keys}
        if canonical is None:
            canonical = current
        elif current != canonical:
            raise ValueError(f'Inconsistent preprocessing/collection duration: {sidecar}')
    return dict(canonical, sequence_length=dataset.sequence_length, input_size=126,
                padding='zeros_at_end', truncation='first_frames', normalization='none',
                valid_lengths='min(source_length, sequence_length)')


def training_loaders(root, manifest_path, batch_size=4, seed=42):
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError('batch_size must be a positive integer')
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    length = manifest.get('sequence_length') if isinstance(manifest, dict) else None
    dataset = VSLDataset(root, sequence_length=length)
    train_indices, val_indices = verify_manifest(dataset, manifest)
    preprocessing = collect_preprocessing(dataset)
    adapter = WithLengths(dataset)
    train = DataLoader(Subset(adapter, train_indices), batch_size=batch_size, shuffle=True,
                       generator=torch.Generator().manual_seed(seed), num_workers=0, drop_last=False)
    val = DataLoader(Subset(adapter, val_indices), batch_size=batch_size, shuffle=False,
                     num_workers=0, drop_last=False)
    # Batched shapes: X=(B,T,126), y=(B,), lengths=(B,).
    return train, val, dataset, manifest, preprocessing
