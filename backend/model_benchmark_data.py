"""Immutable, image-free webcam captures used by both offline model evaluations."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from model_test_profiles import model_schemas

ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
KINDS = ('gesture', 'no_gesture', 'random_motion', 'unknown_sign')


def checked_arrays(features, masks, timestamps):
    features, masks, timestamps = np.asarray(features, dtype=np.float32), np.asarray(masks), np.asarray(timestamps, dtype=np.float64)
    n = len(timestamps)
    if not 20 <= n <= 1200 or features.shape != (n, 126) or masks.shape != (n, 2) or masks.dtype.kind != 'b' \
            or not np.isfinite(features).all() or not np.isfinite(timestamps).all() or not np.all(np.diff(timestamps) > 0) \
            or timestamps[0] < 0 or timestamps[-1] > 10.2 or timestamps[-1] - timestamps[0] < 9:
        raise ValueError('Mẫu cần ít nhất 9 giây hình hợp lệ, timestamp tăng và landmarks hữu hạn. Hãy thu lại.')
    return features, masks, timestamps


def content_hash(features, masks, timestamps):
    return hashlib.sha256(features.astype('<f4').tobytes() + masks.tobytes() +
                          (timestamps - timestamps[0]).astype('<f8').tobytes()).hexdigest()


def checked_metadata(metadata):
    schemas = model_schemas()
    vocabulary = set().union(*(set(s['classes']) for s in schemas.values()))
    if metadata.get('kind') not in KINDS or metadata.get('split') not in ('validation', 'test') \
            or not all(ID.fullmatch(metadata.get(k, '')) for k in ('subject', 'session', 'id')) \
            or metadata.get('condition') not in ('normal', 'low_light', 'busy_background') \
            or metadata.get('preprocessing') != schemas['new']['preprocessing']:
        raise ValueError('Metadata thu mẫu không hợp lệ.')
    label = metadata.get('label')
    if (metadata['kind'] == 'gesture' and label not in vocabulary) or (metadata['kind'] != 'gesture' and label is not None):
        raise ValueError('Nhãn không khớp loại mẫu hoặc không có trong checkpoint.')


def save_capture(root, metadata, features, masks, timestamps):
    features, masks, timestamps = checked_arrays(features, masks, timestamps)
    checked_metadata(metadata)
    root = Path(root).resolve()
    directory = root / metadata['split'] / metadata['subject'] / metadata['session']
    if not directory.resolve().is_relative_to(root):
        raise ValueError('Capture path outside dataset')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (metadata['id'] + '.npz')
    with path.open('xb') as stream:
        np.savez_compressed(stream, features=features, masks=masks, timestamps=timestamps)
    row = {**metadata, 'schema_version': 1, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'content_sha256': content_hash(features, masks, timestamps), 'frames': len(timestamps),
           'capture_fps': (len(timestamps)-1)/(timestamps[-1]-timestamps[0]),
           'max_gap_seconds': float(np.max(np.diff(timestamps))), 'ground_truth': 'user_declared_not_independently_verified'}
    try:
        with path.with_suffix('.json').open('x', encoding='utf-8') as stream:
            json.dump(row, stream, ensure_ascii=False, indent=2, allow_nan=False)
    except Exception:
        # Only remove the new NPZ created above, never existing metadata/data.
        path.unlink()
        raise
    return row, path.relative_to(root).as_posix()


def load_captures(root, split):
    if split not in ('validation', 'test'):
        raise ValueError('Invalid dataset split')
    root = Path(root).resolve()
    result, hashes, groups = [], {}, {}
    for path in sorted(root.glob('*/*/*/*.npz')):
        if not path.resolve().is_relative_to(root):
            raise ValueError('Capture resolves outside dataset')
        row = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        checked_metadata(row)
        if row.get('schema_version') != 1 or row.get('split') != path.relative_to(root).parts[0] \
                or row['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest() \
                or [row['split'], row['subject'], row['session'], row['id']] != [*path.relative_to(root).parts[:3], path.stem]:
            raise ValueError('Capture metadata/checksum mismatch: ' + path.name)
        with np.load(path, allow_pickle=False) as arrays:
            f, m, t = checked_arrays(arrays['features'], arrays['masks'], arrays['timestamps'])
        digest = content_hash(f, m, t)
        if row['frames'] != len(t) or not np.isclose(row['capture_fps'], (len(t)-1)/(t[-1]-t[0])):
            raise ValueError('Capture frame/timing metadata changed')
        if digest != row['content_sha256'] or digest in hashes:
            raise ValueError('Capture duplicated or changed: ' + path.name)
        hashes[digest] = row['split']
        group = (row['subject'], row['session'])
        if group in groups and groups[group] != row['split']:
            raise ValueError('Cùng người/session xuất hiện ở validation và test. Tách session trước khi benchmark.')
        groups[group] = row['split']
        if row['split'] == split:
            result.append({'metadata': row, 'features': f, 'masks': m, 'timestamps': t,
                           'path': path.relative_to(root).as_posix()})
    return result


def dataset_counts(root):
    counts = Counter()
    for path in Path(root).glob('*/*/*/*.json'):
        row = json.loads(path.read_text(encoding='utf-8'))
        counts[(row['split'], row['label'] or row['kind'])] += 1
    return [{'split': split, 'label_or_kind': label, 'count': count} for (split, label), count in sorted(counts.items())]
