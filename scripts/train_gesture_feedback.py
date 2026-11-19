"""Fine-tune a Deafy GRU on a laptop with independent, reviewed sessions."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Deafy_AI_share_ver0'))
from step3_dataset import fit_length, read_sequence
from step5_train import atomic_save, load_checkpoint, run_epoch
from step6_inference_pipeline import validate_preprocessing


def feedback_splits(export, mapping, baseline_hash, validation, test):
    if export.get('schema') != 1 or export.get('format') != 'float32-le:30x126':
        raise ValueError('Unsupported export format')
    if not validation or not test or validation & test:
        raise ValueError('Specify different validation and test sessions')
    splits = {name: [] for name in ('train', 'validation', 'test')}
    seen = set()
    for row in export['samples']:
        if row['status'] not in ('approved', 'trained'):
            continue
        if row['model'] != baseline_hash or row['label'] not in mapping:
            raise ValueError('Sample checkpoint or label does not match baseline')
        raw = base64.b64decode(row['features'], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row['digest'] or digest in seen or len(raw) != 30 * 126 * 4:
            raise ValueError('Damaged, duplicate or incompatible feature sample')
        seen.add(digest)
        sequence = np.frombuffer(raw, dtype='<f4').reshape(30, 126)
        if not np.isfinite(sequence).all() or not np.any(sequence[:, 63:], axis=1).all():
            raise ValueError('Invalid or missing right-hand landmarks')
        session = row['session']
        split = 'validation' if session in validation else 'test' if session in test else 'train'
        splits[split].append((sequence, mapping[row['label']], 30))
    if not splits['train']:
        raise ValueError('Collect at least one approved training session separate from validation and test')
    for split in ('validation', 'test'):
        counts = np.bincount([row[1] for row in splits[split]], minlength=len(mapping))
        if min(counts) < 2:
            raise ValueError(f'{split} requires at least two approved samples for every class')
    return splits


def loader(rows, shuffle=False):
    x, y, lengths = zip(*rows)
    return DataLoader(TensorDataset(torch.from_numpy(np.stack(x)), torch.tensor(y), torch.tensor(lengths)),
                      batch_size=16, shuffle=shuffle, num_workers=0)


def evaluate(model, rows, labels):
    matrix = np.zeros((len(labels), len(labels)), dtype=np.int64)
    model.eval()
    with torch.inference_mode():
        for x, y, lengths in loader(rows):
            predicted = model(x, lengths).argmax(dim=1).numpy()
            np.add.at(matrix, (y.numpy(), predicted), 1)
    true_positive = matrix.diagonal()
    precision = true_positive / np.maximum(1, matrix.sum(axis=0))
    recall = true_positive / np.maximum(1, matrix.sum(axis=1))
    f1 = 2 * precision * recall / np.maximum(1e-12, precision + recall)
    return {'accuracy': float(true_positive.sum() / matrix.sum()), 'macro_f1': float(f1.mean()),
            'classes': {label: {'precision': float(precision[i]), 'recall': float(recall[i]),
                                'f1': float(f1[i]), 'support': int(matrix[i].sum())} for i, label in enumerate(labels)},
            'confusion_matrix': matrix.tolist()}


def run(args):
    if not 1 <= args.epochs <= 100:
        raise ValueError('Epochs must be between 1 and 100')
    torch.manual_seed(42)
    torch.set_num_threads(2)
    model, checkpoint = load_checkpoint(args.baseline)
    preprocessing = validate_preprocessing(checkpoint)
    if preprocessing['sequence_length'] != 30:
        raise ValueError('Feedback was recorded for a 30-frame GRU')
    mapping = checkpoint['class_to_idx']
    baseline_hash = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    feedback = args.feedback.read_bytes()
    splits = feedback_splits(json.loads(feedback), mapping, baseline_hash,
                             set(args.validation_session), set(args.test_session))
    original = []
    original_hashes = {row['path']: row['sha256']
                       for split in ('train', 'validation')
                       for row in checkpoint['split_provenance']['manifest'][split]}
    root = args.original.resolve()
    for relative, expected in sorted(original_hashes.items()):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Invalid path in baseline provenance')
        if not path.is_file():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            continue
        sequence = read_sequence(path)
        original.append((fit_length(sequence, 30), mapping[Path(relative).parts[0]], min(len(sequence), 30)))
    if not original:
        raise ValueError('No original training samples matched the baseline')
    splits['train'] = original + splits['train']
    counts = np.bincount([row[1] for row in splits['train']], minlength=len(mapping))
    if min(counts) < 2:
        missing = [label for label, index in mapping.items() if counts[index] < 2]
        raise ValueError(f'Collect at least two approved training samples for classes lacking old data: {missing}')

    # Keep near-identical model inputs out of different partitions, including the old data.
    for left, right in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
        reference = np.stack([row[0] for row in splits[left]])
        for sequence, _, _ in splits[right]:
            if np.any(np.sqrt(np.mean((reference - sequence) ** 2, axis=(1, 2))) < .012):
                raise ValueError(f'Near-duplicate samples found across {left} and {right}')

    labels = sorted(mapping, key=mapping.get)
    baseline = evaluate(model, splits['test'], labels)
    optimizer = torch.optim.Adam(model.parameters(), lr=.0003)
    training, validation = loader(splits['train'], True), loader(splits['validation'])
    best_loss = float('inf')
    for epoch in range(1, args.epochs + 1):
        run_epoch(model, training, 'cpu', optimizer)
        score = run_epoch(model, validation, 'cpu')['loss']
        if score < best_loss:
            best_loss = score
            best = {name: weight.detach().clone() for name, weight in model.state_dict().items()}
        print(f'EPOCH {epoch}/{args.epochs}', flush=True)
    model.load_state_dict(best)
    result = evaluate(model, splits['test'], labels)
    watched = [label for label in labels if label.casefold() in ('xin_chao', 'tam_biet', 'chao', 'bat_den', 'tat_den')]
    passed = (result['accuracy'] >= baseline['accuracy'] - .02 and result['macro_f1'] >= baseline['macro_f1'] - .02
              and all(result['classes'][label]['f1'] >= baseline['classes'][label]['f1'] - .05 for label in watched))
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output / 'candidate.pth'
    atomic_save(output, {**checkpoint, 'model_state_dict': best, 'personalization_baseline_sha256': baseline_hash}, tensor=True)
    report = {'baseline_sha256': baseline_hash, 'candidate_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'feedback_sha256': hashlib.sha256(feedback).hexdigest(), 'trained_at': datetime.now(timezone.utc).isoformat(),
              'baseline': baseline, 'candidate': result, 'labels': labels, 'watched_labels': watched,
              'passes_quality_gate': passed, 'samples': {key: len(rows) for key, rows in splits.items()},
              'original_available': len(original), 'original_expected': len(original_hashes),
              'validation_sessions': args.validation_session, 'test_sessions': args.test_session}
    atomic_save(args.output / 'evaluation.json', report)
    print(f'Quality gate: {"PASS" if passed else "FAIL"}. Report: {args.output / "evaluation.json"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('baseline', 'original', 'feedback', 'output'):
        parser.add_argument(f'--{argument}', type=Path, required=True)
    parser.add_argument('--validation-session', action='append', required=True)
    parser.add_argument('--test-session', action='append', required=True)
    parser.add_argument('--epochs', type=int, default=5)
    run(parser.parse_args())
