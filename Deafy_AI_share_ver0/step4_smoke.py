"""Verify GRU forward shapes on synthetic tensors and real data, without training."""
import argparse
from pathlib import Path
import sys

import torch
from step3_dataset import DEFAULT_DATA_ROOT, create_dataloaders
from step4_model import GRUClassifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        torch.manual_seed(args.seed)
        train, val, dataset = create_dataloaders(args.data_dir, batch_size=args.batch_size, seed=args.seed)
        # Dataset returns (X,y), without aligned lengths in shuffled batches.
        # Never guess lengths from zero landmarks: an absent hand legitimately contains zeros.
        short = [s.path.name for s in dataset.samples if s.source_length < dataset.sequence_length]
        if short:
            raise ValueError("Padded real samples require aligned valid lengths from a loader adapter. "
                             f"Step4 smoke stops safely; first sample: {short[0]}")
        model = GRUClassifier(num_classes=len(dataset.class_to_idx))
        model.eval()
        print(f"PyTorch: {torch.__version__}")
        print(f"Classes: {dataset.class_to_idx}")
        print(model)
        print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")
        print("Random initialization; predictions are not meaningful before training.")
        shapes = {}

        def capture_shapes(module, inputs, output):
            sequence_output, hidden = output
            shapes['output'] = tuple(sequence_output.shape)
            shapes['hidden'] = tuple(hidden.shape)

        handle = model.gru.register_forward_hook(capture_shapes)
        try:
            with torch.inference_mode():
                # Synthetic X shape: (B=4, T=30, Input_size=126).
                dummy = torch.randn(4, 30, 126)
                logits = model(dummy)  # Shape: (4, C=3 with current dataset).
                print(f"Synthetic input: {tuple(dummy.shape)}")
                print(f"GRU output: {shapes['output']}")
                print(f"GRU h_n: {shapes['hidden']}")
                print(f"Last hidden: {(dummy.shape[0], model.hidden_size)}")
                print(f"Synthetic logits: {tuple(logits.shape)}")
                for name, loader in (("Train", train), ("Validation", val)):
                    checked = 0
                    for batch_index, (x, y) in enumerate(loader):
                        # X: (B,30,126), y: (B,), logits: (B,num_classes).
                        logits = model(x)
                        expected = (len(y), len(dataset.class_to_idx))
                        if logits.shape != expected or not torch.isfinite(logits).all():
                            raise ValueError(f"{name} logits invalid: expected {expected}")
                        if batch_index == 0:
                            probabilities = logits.softmax(dim=-1)  # Shape: (B,C); display check only.
                            torch.testing.assert_close(probabilities.sum(dim=1), torch.ones(len(y)))
                            print(f"{name}: X={tuple(x.shape)} -> logits={tuple(logits.shape)} {logits.dtype}")
                        checked += len(y)
                    print(f"{name} samples checked: {checked}")
        finally:
            handle.remove()
        print("PASS: GRU forward shapes and finite logits verified. No training or weights saved.")
    except (ValueError, OSError, RuntimeError, AssertionError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
