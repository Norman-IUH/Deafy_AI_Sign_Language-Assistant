"""Prepare verified validation tensors and PyTorch logits for the mobile parity test."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Deafy_AI_share_ver0'))
from step5_train import load_checkpoint
from step6_inference_pipeline import validate_preprocessing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('apk', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--android-sample', type=Path, action='append', default=[])
    parser.add_argument('--data', type=Path, default=ROOT / 'data/data/raw')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    model, state = load_checkpoint(args.checkpoint)
    digest = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    with ZipFile(args.apk) as apk:
        for name in ('model2.json', 'model2.onnx', 'model2-gru.bin', 'ort-wasm-simd-threaded.wasm'):
            (args.output / name).write_bytes(apk.read('assets/public/mobile/' + name))
    manifest = json.loads((args.output / 'model2.json').read_text(encoding='utf-8'))
    assert manifest['sha256'] == digest, 'APK checkpoint does not match baseline'
    assert manifest['preprocessing'] == validate_preprocessing(state)
    mapping = {label['id']: index for index, label in enumerate(manifest['labels'])}
    assert mapping == state['class_to_idx'], 'Label indices differ'
    split = json.loads(args.checkpoint.with_name('split_manifest.json').read_text(encoding='utf-8'))
    assert split['class_to_idx'] == mapping
    pairs, missing = [], 0
    for entry in split['validation']:
        path = args.data / entry['path']
        if not path.is_file():
            missing += 1
            continue
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], f'Changed validation sample: {path.name}'
        pairs.append((np.load(path, allow_pickle=False), entry['label'], 'validation'))
    for path in args.android_sample:
        sample = json.loads(path.read_text(encoding='utf-8-sig'))
        assert sample['checkpoint'] == digest and sample['shape'] == [30, 126]
        vector = np.frombuffer(base64.b64decode(sample['keypoints'], validate=True), dtype='<f4').reshape(30, 126)
        pairs.append((vector, mapping[sample['label']], 'android'))
    rows = []
    with torch.inference_mode():
        for values, label, group in pairs:
            assert values.shape in ((30, 126), (1, 30, 126)) and np.isfinite(values).all()
            tensor = np.ascontiguousarray(values.reshape(1, 30, 126), dtype='<f4')
            logits = model(torch.from_numpy(tensor))[0].tolist()
            rows.append({'tensor': base64.b64encode(tensor.tobytes()).decode(), 'label': label, 'group': group, 'logits': logits})
    assert rows, 'No validation or labeled Android tensors available'
    (args.output / 'parity.json').write_text(json.dumps({'checkpoint': digest, 'rows': rows}), encoding='utf-8')
    coverage = len({label for _, label, group in pairs if group == 'validation'})
    print(f'{len(rows)} tensors, {missing} missing validation files, {coverage}/{len(mapping)} validation labels, PyTorch {torch.__version__}, {digest}')


if __name__ == '__main__':
    main()
