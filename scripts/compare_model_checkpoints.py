"""Compare verified checkpoints on the same available samples, excluding both training sets."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'Deafy_AI_share_ver0'))

import numpy as np
import torch
from model_test_profiles import PROFILES, checkpoint_path
from step3_dataset import read_sequence, fit_length
from step5_train import load_checkpoint
from step6_inference_pipeline import validate_preprocessing


def compare(data_root, output):
    torch.set_num_threads(1)
    checkpoints, models, manifests = {}, {}, {}
    for name in PROFILES:
        path = checkpoint_path(name)
        models[name], checkpoints[name] = load_checkpoint(path)
        validate_preprocessing(checkpoints[name])
        manifests[name] = json.loads(path.with_name('split_manifest.json').read_text(encoding='utf-8'))
        embedded = checkpoints[name]['split_provenance']['manifest']
        if manifests[name] != embedded:
            raise ValueError('External split differs from checkpoint provenance: ' + name)
    common = set.intersection(*(set(c['class_to_idx']) for c in checkpoints.values()))
    trained = {row['sha256'] for manifest in manifests.values() for row in manifest['train']}
    validation = {name: {r['sha256'] for r in m['validation']} for name, m in manifests.items()}
    candidates, skipped, seen = [], Counter(), set()
    data_root = Path(data_root).resolve()
    for path in sorted(data_root.glob('*/*.npy')):
        if not path.resolve().is_relative_to(data_root):
            raise ValueError('Sample resolves outside evaluation directory')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.parent.name not in common:
            skipped['label_not_shared'] += 1
        elif digest in trained:
            skipped['present_in_training'] += 1
        elif digest in seen:
            skipped['duplicate_sha256'] += 1
        else:
            sidecar = path.with_suffix('.json')
            if not sidecar.is_file():
                skipped['missing_collection_metadata'] += 1
                continue
            metadata = json.loads(sidecar.read_text(encoding='utf-8'))
            for key in ('feature_order', 'mirrored_before_inference', 'coordinates', 'duration_seconds', 'sequence_length'):
                if metadata.get(key) != checkpoints['new']['preprocessing'][key]:
                    raise ValueError(f'Evaluation sample preprocessing differs: {path.name}: {key}')
            sequence = fit_length(read_sequence(path), 30)
            candidates.append((path, digest, sequence, metadata))
            seen.add(digest)
    report = {'purpose': 'same input comparison, no training', 'sample_count': len(candidates),
              'shared_classes': sorted(common), 'skipped': dict(skipped),
              'class_counts': dict(Counter(p.parent.name for p, *_ in candidates)),
              'signers': dict(Counter(m.get('signer', 'unknown') for *_, m in candidates)),
              'limitation': 'Excluded both training sets by SHA256; may include validation used for checkpoint selection. Same known signers/sessions, not independent-person accuracy. No webcam accuracy inferred.',
              'models': {}, 'samples': [{'path': p.relative_to(data_root).as_posix(), 'sha256': h} for p, h, *_ in candidates],
              'pi_deployment': 'NOT APPROVED; Windows webcam evaluation and user approval still required'}
    strict = [(p, h) for p, h, *_ in candidates if all(h not in hashes for hashes in validation.values())]
    report['strict_holdout'] = {'count': len(strict), 'class_counts': dict(Counter(p.parent.name for p, _ in strict)),
                              'limitation': 'Absent by SHA256 from both training and validation manifests; available classes/signers may be limited. Not an independent-person test.'}
    strict_hashes = {h for _, h in strict}
    with torch.inference_mode():
        for name, model in models.items():
            c = checkpoints[name]
            inverse = {i: label for label, i in c['class_to_idx'].items()}
            for _ in range(8):
                model(torch.zeros(1, 30, 126))
            correct, strict_correct, delays, confidences, confusion = 0, 0, [], [], Counter()
            predictions = []
            for path, digest, sequence, metadata in candidates:
                x = torch.from_numpy(sequence[None])
                started = perf_counter()
                logits = model(x)
                delays.append((perf_counter()-started)*1000)
                if logits.shape != (1, len(inverse)) or not torch.isfinite(logits).all():
                    raise ValueError('Invalid model output')
                probabilities = logits.softmax(1)[0]
                predicted = inverse[int(probabilities.argmax())]
                confidences.append(float(probabilities.max()))
                correct += predicted == path.parent.name
                strict_correct += digest in strict_hashes and predicted == path.parent.name
                confusion[(path.parent.name, predicted)] += 1
                predictions.append({'id': digest, 'expected': path.parent.name, 'predicted': predicted,
                                    'confidence': float(probabilities.max()), 'latency_ms': delays[-1],
                                    'subject': metadata.get('signer'), 'condition': 'not_recorded',
                                    'strict_holdout': digest in strict_hashes, 'events': None})
            report['models'][name] = {'sha256': PROFILES[name]['sha256'], 'path': PROFILES[name]['path'],
                'model_config': c['model_config'], 'class_to_idx': c['class_to_idx'], 'preprocessing': c['preprocessing'],
                'training_config': c['training_config'], 'best_epoch': c['best_epoch'],
                'reported_validation_accuracy': c['best_val_accuracy'], 'parameters': sum(p.numel() for p in model.parameters()),
                'sample_count': len(candidates), 'correct_top1': correct,
                'top1_accuracy': correct/len(candidates) if candidates else None,
                'strict_holdout_correct': strict_correct,
                'strict_holdout_accuracy': strict_correct/len(strict) if strict else None,
                'forward_ms_median': float(np.median(delays)) if delays else None,
                'forward_ms_p95': float(np.percentile(delays, 95)) if delays else None,
                'softmax_mean': float(np.mean(confidences)) if confidences else None,
                'above_original_threshold': sum(p >= .7 for p in confidences),
                'confusion': [{'expected': expected, 'predicted': predicted, 'count': count} for (expected, predicted), count in sorted(confusion.items())],
                'also_in_checkpoint_validation': sum(h in validation[name] for _, h, *_ in candidates)}
            report['models'][name]['predictions'] = predictions
            assert 0 <= strict_correct <= len(strict) <= len(candidates)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=ROOT / 'data/data/raw')
    parser.add_argument('--output', type=Path, default=ROOT / '.tools/model-test/comparison.json')
    args = parser.parse_args()
    result = compare(args.data_root, args.output)
    print(json.dumps({'sample_count': result['sample_count'], 'skipped': result['skipped'],
        'models': {name: {k: v for k, v in model.items() if k in ('correct_top1','top1_accuracy','forward_ms_median','forward_ms_p95','model_config')} for name, model in result['models'].items()},
        'report': str(args.output), 'limitation': result['limitation']}, ensure_ascii=False))
