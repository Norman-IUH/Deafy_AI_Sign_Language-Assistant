"""Build a reproducible template baseline; hold out the last 6 clips per label."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from landmark_recognition import FEATURE_ORDER, TemplateModel, checked_sequence


def train(source, output):
    samples, targets, labels, metadata, paths = [], [], [], [], []
    for folder in sorted(source.iterdir()):
        if not folder.is_dir():
            continue
        files = sorted(folder.glob('*.npy'))
        if len(files) < 10:
            raise ValueError(f'{folder.name}: cần ít nhất 10 mẫu để train và kiểm tra.')
        label_index = len(labels)
        labels.append(folder.name)
        for path in files:
            info = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
            if (info['label'] != folder.name or info['feature_order'] != FEATURE_ORDER
                    or info['mirrored_before_inference'] is not True
                    or info['sequence_length'] != 30 or info['duration_seconds'] != 3.0
                    or info['min_handedness_score'] != .7 or info['mediapipe_version'] != '0.10.21'
                    or info['sampling'] != 'nearest frame on uniform grid; no interpolation'):
                raise ValueError(f'Metadata không tương thích: {path}')
            array = np.load(path, allow_pickle=False)
            if array.shape != (1, 30, 126):
                raise ValueError(f'Shape không tương thích: {path}: {array.shape}')
            samples.append(checked_sequence(array[0]))
            targets.append(label_index)
            metadata.append(info)
            paths.append(str(path.relative_to(source)))
    if len(labels) < 2:
        raise ValueError('Cần dữ liệu của ít nhất 2 ký hiệu.')
    samples, targets = np.stack(samples), np.array(targets)
    held_out = np.zeros(len(samples), dtype=bool)
    for label_index in range(len(labels)):
        held_out[np.flatnonzero(targets == label_index)[-6:]] = True
    training, training_targets = samples[~held_out], targets[~held_out]
    radii = []
    for label_index in range(len(labels)):
        group = training[training_targets == label_index]
        nearest = []
        for i, sequence in enumerate(group):
            distances = np.sqrt(np.mean((group - sequence) ** 2, axis=(1, 2)))
            distances[i] = np.inf
            nearest.append(float(distances.min()))
        radii.append(max(.015, float(np.quantile(nearest, .95)) * 1.3))
    model = TemplateModel(training, training_targets, labels, radii)
    predictions = [model.predict(s) for s in samples[held_out]]
    actual = [labels[i] for i in targets[held_out]]
    correct = [p['label'] == label for p, label in zip(predictions, actual)]
    accepted = [p['accepted'] for p in predictions]
    report = {
        'method': 'nearest sequence template (RMSE), distance + margin rejection, 2 stable live predictions',
        'samples': len(samples), 'labels': dict(Counter(labels[i] for i in targets)),
        'signers': dict(Counter(m['signer'] for m in metadata)),
        'distance_thresholds': dict(zip(labels, radii)),
        'training_samples': len(training), 'validation_samples': sum(held_out).item(),
        'split': 'Last 6 recordings by filename per label, excluded from saved templates and threshold fitting.',
        'validation_top1_accuracy': float(np.mean(correct)),
        'validation_accepted': sum(accepted),
        'validation_accepted_correct': sum(a and c for a, c in zip(accepted, correct)),
        'limitations': 'One signer; same recording sessions. No independent signer, live accuracy, or unknown-gesture validation. Confidence is template similarity, not probability.',
        'validation': [{'file': path, 'actual': label, **p}
                       for path, label, p in zip(np.array(paths)[held_out].tolist(), actual, predictions)],
        'training_files': np.array(paths)[~held_out].tolist(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, schema_version=1, feature_order=FEATURE_ORDER,
                        samples=training, targets=training_targets, labels=np.array(labels), radii=np.array(radii))
    output.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('validation', 'training_files')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root.parent / 'data/data/raw')
    parser.add_argument('--output', type=Path, default=root / 'data/landmark_templates.npz')
    args = parser.parse_args()
    train(args.source, args.output)
