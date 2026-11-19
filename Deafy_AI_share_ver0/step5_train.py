"""Step 5: train/validate GRU and save best validation-loss checkpoint."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import uuid

import numpy as np
import torch
from torch import nn

from step3_dataset import DEFAULT_DATA_ROOT
from step4_model import GRUClassifier
from step5_training_data import training_loaders

PROJECT = Path(__file__).resolve().parent


def atomic_save(path, payload, tensor=False):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        if tensor:
            torch.save(payload, temporary)
        else:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_epoch(model, loader, device, optimizer=None):
    training = optimizer is not None
    model.train(training)
    criterion = nn.CrossEntropyLoss()  # raw logits (B,C), integer targets (B,).
    loss_sum, correct, count = 0.0, 0, 0
    context = torch.enable_grad() if training else torch.inference_mode()
    with context:
        for x, y, lengths in loader:
            x, y = x.to(device), y.to(device)  # Shapes: (B,T,126), (B,).
            # lengths shape (B,), kept on CPU for pack_padded_sequence.
            if training:
                optimizer.zero_grad(set_to_none=True)
            logits = model(x, lengths)  # Shape: (B,num_classes); no softmax before loss.
            loss = criterion(logits, y)  # Shape: (), mean loss over this batch.
            if not torch.isfinite(loss):
                raise ValueError('Non-finite loss; training stopped')
            if training:
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0, error_if_nonfinite=True)
                optimizer.step()
            batch = len(y)
            loss_sum += loss.item() * batch
            correct += (logits.argmax(dim=1) == y).sum().item()
            count += batch
    if count == 0:
        raise ValueError('Empty loader')
    metrics = dict(loss=loss_sum / count, accuracy=correct / count, samples=count)
    if not all(math.isfinite(metrics[k]) for k in ('loss', 'accuracy')):
        raise ValueError('Non-finite epoch metrics')
    return metrics


def load_checkpoint(path, device='cpu'):
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    if checkpoint.get('schema_version') != 1:
        raise ValueError('Unsupported checkpoint schema')
    config, mapping = checkpoint['model_config'], checkpoint['class_to_idx']
    if (not isinstance(mapping, dict) or sorted(mapping.values()) != list(range(len(mapping)))
            or config['num_classes'] != len(mapping) or config['input_size'] != 126):
        raise ValueError('Invalid checkpoint class mapping/model config')
    model = GRUClassifier(**config).to(device)
    model.load_state_dict(checkpoint['model_state_dict'], strict=True)
    if not all(torch.isfinite(p).all() for p in model.parameters()):
        raise ValueError('Checkpoint contains non-finite weights')
    model.eval()
    return model, checkpoint


def fit(data_dir, split_path, run_dir=None, epochs=3, batch_size=4, lr=0.001,
        seed=42, device='cpu'):
    if not isinstance(epochs, int) or isinstance(epochs, bool) or epochs < 1:
        raise ValueError('epochs must be a positive integer')
    if not math.isfinite(lr) or lr <= 0:
        raise ValueError('lr must be finite and positive')
    device = torch.device(device)
    if device.type == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA unavailable; use --device cpu')
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    train, val, dataset, manifest, preprocessing = training_loaders(data_dir, split_path, batch_size, seed)
    config = dict(num_classes=len(dataset.class_to_idx), input_size=126, hidden_size=64, num_layers=2)
    model = GRUClassifier(**config).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    if run_dir is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run_dir = PROJECT / 'artifacts' / 'step5' / ('run_' + stamp + '_' + uuid.uuid4().hex[:8])
    run_dir = Path(run_dir).resolve()
    if run_dir.is_relative_to(dataset.root):
        raise ValueError('run_dir must be outside raw data directory')
    run_dir.mkdir(parents=True, exist_ok=False)  # Never reuse/overwrite an earlier run.
    split_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    provenance = dict(manifest_sha256=hashlib.sha256(split_bytes).hexdigest(),
                      hash_format='canonical JSON sort_keys=True separators=comma:colon', manifest=manifest)
    run_config = dict(epochs=epochs, batch_size=batch_size, learning_rate=lr, seed=seed,
                      device=str(device), optimizer='Adam', gradient_clip_norm=5.0,
                      torch_version=str(torch.__version__), selection='lowest_val_loss',
                      validation_limitation='Sample split from same signer/sessions; pipeline experiment only.')
    atomic_save(run_dir / 'run_config.json', run_config)
    atomic_save(run_dir / 'split_manifest.json', manifest)
    print(f'Run directory: {run_dir}', flush=True)
    print(f'Classes: {dataset.class_to_idx} | Train: {len(train.dataset)} | Validation: {len(val.dataset)}')
    print('WARNING: validation is same-signer/session pipeline experiment; not new-person accuracy.')
    fixed_x, _, fixed_lengths = next(iter(val))
    fixed_x = fixed_x.to(device)
    history, best_loss, best_epoch, best_logits = [], float('inf'), 0, None
    best_path = run_dir / 'best_model.pth'
    for epoch in range(1, epochs + 1):
        train_metrics = run_epoch(model, train, device, optimizer)
        val_metrics = run_epoch(model, val, device)
        row = dict(epoch=epoch, train_loss=train_metrics['loss'], train_accuracy=train_metrics['accuracy'],
                   val_loss=val_metrics['loss'], val_accuracy=val_metrics['accuracy'])
        history.append(row)
        improved = val_metrics['loss'] < best_loss
        if improved:
            best_loss, best_epoch = val_metrics['loss'], epoch
            with torch.inference_mode():
                best_logits = model(fixed_x, fixed_lengths).detach().cpu().clone()
            checkpoint = dict(schema_version=1,
                              model_state_dict={k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                              model_config=config, class_to_idx=dataset.class_to_idx,
                              preprocessing=preprocessing, split_provenance=provenance,
                              best_epoch=best_epoch, best_val_loss=best_loss,
                              best_val_accuracy=val_metrics['accuracy'], training_config=run_config)
            atomic_save(best_path, checkpoint, tensor=True)
        atomic_save(run_dir / 'history.json', history)
        print(f"Epoch {epoch:03d}/{epochs} | train_loss={row['train_loss']:.4f} "
              f"train_acc={row['train_accuracy']:.1%} | val_loss={row['val_loss']:.4f} "
              f"val_acc={row['val_accuracy']:.1%}" + (' | BEST saved' if improved else ''), flush=True)
    reloaded, checkpoint = load_checkpoint(best_path, device)
    with torch.inference_mode():
        reloaded_logits = reloaded(fixed_x, fixed_lengths).cpu()
    torch.testing.assert_close(reloaded_logits, best_logits)
    reloaded_metrics = run_epoch(reloaded, val, device)
    if not math.isclose(reloaded_metrics['loss'], best_loss, rel_tol=1e-6, abs_tol=1e-7):
        raise ValueError('Reloaded validation loss differs from best checkpoint')
    summary = dict(best_epoch=best_epoch, best_val_loss=best_loss,
                   best_val_accuracy=checkpoint['best_val_accuracy'], reload_verified=True,
                   completed_epochs=len(history), checkpoint=str(best_path))
    atomic_save(run_dir / 'summary.json', summary)
    print(f'Best epoch: {best_epoch} | best_val_loss={best_loss:.6f}')
    print(f'Checkpoint: {best_path}')
    print('PASS: training completed, best checkpoint reloaded and verified. Stop before Step 6.')
    return run_dir, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument('--split', type=Path, default=PROJECT / 'artifacts' / 'step3_split.json')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--lr', type=float, default=0.001)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    args = parser.parse_args()
    torch.set_num_threads(1)  # Small CPU sequences: avoid excessive thread overhead.
    try:
        fit(args.data_dir, args.split, args.run_dir, args.epochs, args.batch_size,
            args.lr, args.seed, args.device)
    except KeyboardInterrupt:
        print('\nStopped. Completed history and last saved best checkpoint remain in run directory.')
        return 130
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, AssertionError) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
