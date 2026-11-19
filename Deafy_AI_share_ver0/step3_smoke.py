"""Inspect Dataset/DataLoader on saved NPY files; no camera or model training."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import torch
from step3_dataset import DEFAULT_DATA_ROOT, create_dataloaders, split_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--sequence-length", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parent / "artifacts" / "step3_split.json")
    args = parser.parse_args()
    try:
        train, val, dataset = create_dataloaders(args.data_dir, args.sequence_length,
                                                args.batch_size, args.val_ratio, args.seed)
        print(f"PyTorch: {torch.__version__}")
        print(f"Data: {dataset.root}")
        print(f"Classes: {dataset.class_to_idx}")
        print(f"Total: {len(dataset)} | Train: {len(train.dataset)} | Validation: {len(val.dataset)}")
        for name, loader in (("Train", train), ("Validation", val)):
            counts = Counter(dataset.samples[i].label for i in loader.dataset.indices)
            print(f"{name} counts: " + str({k: counts[v] for k, v in dataset.class_to_idx.items()}))
            seen = 0
            for batch_idx, (x, y) in enumerate(loader):
                # X: (Batch_size, Sequence_length, Input_size=126); y: (Batch_size,).
                if x.shape[1:] != (args.sequence_length, 126) or y.shape != (x.shape[0],):
                    raise ValueError("Unexpected batch shape")
                if x.dtype != torch.float32 or y.dtype != torch.long or not torch.isfinite(x).all():
                    raise ValueError("Unexpected batch dtype or non-finite coordinates")
                if batch_idx == 0:
                    print(f"{name} first batch: X={tuple(x.shape)} {x.dtype}, y={tuple(y.shape)} {y.dtype}")
                    print(f"{name} labels: {y.tolist()}")
                seen += len(y)
            if seen != len(loader.dataset):
                raise ValueError("Loader lost samples")
        padded = sum(s.source_length < args.sequence_length for s in dataset.samples)
        truncated = sum(s.source_length > args.sequence_length for s in dataset.samples)
        print(f"Padded: {padded} | Truncated: {truncated}")
        manifest = split_manifest(dataset, train.dataset.indices, val.dataset.indices, args.seed, args.val_ratio)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        # Keep an existing manifest if input membership/settings differ.
        text = json.dumps(manifest, ensure_ascii=False, indent=2)
        if args.manifest.exists():
            if json.loads(args.manifest.read_text(encoding="utf-8")) != manifest:
                raise ValueError("Existing manifest differs. Choose a new --manifest path for this dataset/settings.")
        else:
            with args.manifest.open("x", encoding="utf-8") as stream:
                stream.write(text)
        print(f"Split manifest: {args.manifest.resolve()}")
        print("PASS: all batches checked; raw data unchanged. Stop here before Step 4.")
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
