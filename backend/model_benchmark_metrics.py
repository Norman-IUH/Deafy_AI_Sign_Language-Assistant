"""Descriptive metrics with explicit missing denominators and data coverage."""
from collections import Counter
from statistics import mean
import numpy as np


def latency(values):
    return {'count': len(values), 'mean': mean(values) if values else None,
            'p95': float(np.percentile(values, 95)) if values else None}


def standalone_candidate(old, new):
    for name, winner, other in [('new', new, old), ('old', old, new)]:
        a, b = winner['macro_f1_all_classes'], other['macro_f1_all_classes']
        p, q = winner['inference_latency_ms']['p95'], other['inference_latency_ms']['p95']
        if a is not None and b is not None and a-b >= .02 and p is not None and q is not None \
                and winner['false_positive_rate'] is not None and other['false_positive_rate'] is not None \
                and winner['false_positive_rate'] <= other['false_positive_rate'] and p <= 1.2*q:
            return name
    return None


def metrics(rows, labels):
    positive = [r for r in rows if r['expected'] in labels]
    matrix = Counter((r['expected'], r['predicted'] or '__miss__') for r in positive)
    per_class = {}
    for label in labels:
        tp = matrix[label, label]
        support = sum(n for (expected, _), n in matrix.items() if expected == label)
        predicted = sum(n for (_, actual), n in matrix.items() if actual == label)
        fp, fn = predicted-tp, support-tp
        per_class[label] = {'support': support, 'predicted': predicted,
                            'precision': tp/predicted if predicted else None,
                            'recall': tp/support if support else None,
                            'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}
    observed = [v['f1'] for v in per_class.values() if v['support']]
    streaming = [r for r in rows if r.get('events') is not None]
    positive_streams = [r for r in streaming if r['expected'] in labels]
    negatives = [r for r in streaming if r['expected'] is None]
    negative_kinds = {}
    for kind in ('no_gesture', 'random_motion', 'unknown_sign'):
        selected = [r for r in negatives if r.get('kind') == kind]
        negative_kinds[kind] = {'count': len(selected), 'false_positive_rate': sum(bool(r['events']) for r in selected)/len(selected) if selected else None}
    correct_latency = [r['first_confirmed_seconds'] for r in positive_streams if r['predicted'] == r['expected'] and r.get('first_confirmed_seconds') is not None]
    return {'positive_count': len(positive), 'observed_classes': sum(v['support'] > 0 for v in per_class.values()),
            'requested_classes': len(labels),
            'accuracy': sum(r['predicted'] == r['expected'] for r in positive)/len(positive) if positive else None,
            'macro_f1_observed': mean(observed) if observed else None,
            'macro_f1_all_classes': mean(observed) if observed and len(observed) == len(labels) else None,
            'per_class': per_class,
            'confusion': [{'expected': e, 'predicted': p, 'count': n} for (e, p), n in sorted(matrix.items())],
            'negative_count': len(negatives), 'negative_kinds': negative_kinds,
            'false_positive_rate': sum(bool(r['events']) for r in negatives)/len(negatives) if negatives else None,
            'false_events_per_minute': sum(len(r['events']) for r in negatives)/(sum(r['duration_seconds'] for r in negatives)/60) if negatives else None,
            'no_confirmation_rate': sum(not r['events'] for r in positive_streams)/len(positive_streams) if positive_streams else None,
            'duplicate_clip_rate': sum(any(n > 1 for n in Counter(e['label'] for e in r['events']).values()) for r in positive_streams)/len(positive_streams) if positive_streams else None,
            'correct_confirmation_latency_seconds_from_cue': latency(correct_latency),
            'inference_latency_ms': latency([d for r in rows for d in r.get('inference_ms', ([r['latency_ms']] if 'latency_ms' in r else []))])}
