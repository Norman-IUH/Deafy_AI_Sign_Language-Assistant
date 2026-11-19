"""Export the supplied Model 2 and compare against real local keypoint samples."""
import hashlib
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import onnx
import onnxruntime as ort
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'Deafy_AI_share_ver0'), str(ROOT / 'backend')]
from step5_train import load_checkpoint
from step6_inference_pipeline import validate_preprocessing
from sign_vocabulary import LABEL_TEXT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--expected-sha256', required=True, help='Trusted hash from the active Pi model')
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    source = checkpoint.relative_to(ROOT).as_posix()
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if digest != args.expected_sha256.lower():
        parser.error('Checkpoint does not match the expected Pi SHA-256')
    torch.set_num_threads(1)
    model, state = load_checkpoint(checkpoint)
    settings = validate_preprocessing(state)
    model.eval()
    assert model.gru.hidden_size == 64 and model.gru.num_layers == 2

    target = ROOT / 'Android_App/public/mobile'
    target.mkdir(exist_ok=True)
    names = [f'gru.{kind}_l{i}' for i in range(2)
             for kind in ('weight_ih', 'weight_hh', 'bias_ih', 'bias_hh')]
    names += ['fc.weight', 'fc.bias']
    params = model.state_dict()
    np.concatenate([params[name].detach().cpu().numpy().ravel() for name in names]).astype('<f4').tofile(target / 'model2-gru.bin')
    path = target / 'model2.onnx'
    torch.onnx.export(model, torch.zeros(1, 30, 126), str(path), input_names=['sequence'],
                      output_names=['logits'], opset_version=17, dynamo=False)
    onnx.checker.check_model(str(path))
    session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    labels = sorted(state['class_to_idx'], key=state['class_to_idx'].get)
    counts = dict.fromkeys(labels, 0)
    worst = 0.0
    for label in labels:
        samples = sorted((ROOT / 'data/data/raw' / label).glob('*.npy'))
        for sample in samples[:6]:
            x = np.load(sample, allow_pickle=False).astype(np.float32)
            if x.shape not in ((30, 126), (1, 30, 126)):
                continue
            x = x.reshape(1, 30, 126)
            with torch.inference_mode():
                expected = model(torch.from_numpy(x)).softmax(1).numpy()
            logits = session.run(None, {'sequence': x})[0]
            actual = torch.from_numpy(logits).softmax(1).numpy()
            worst = max(worst, float(np.max(np.abs(actual - expected))))
            assert actual.argmax() == expected.argmax(), sample.name
            np.testing.assert_allclose(actual, expected, atol=1e-5, rtol=1e-5)
            counts[label] += 1
    assert sum(counts.values()) > 0, 'No real 30x126 data available'
    (target / 'model2.json').write_text(json.dumps({
        'sha256': digest,
        'version': checkpoint.parent.name,
        'checkpoint_source': source,
        'onnx_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'preprocessing': settings,
        'gru_sha256': hashlib.sha256((target / 'model2-gru.bin').read_bytes()).hexdigest(),
        'labels': [{'id': label, 'text': LABEL_TEXT.get(label, label.replace('_', ' '))} for label in labels],
    }, ensure_ascii=False), encoding='utf-8')
    print('Samples', sum(counts.values()), 'classes covered', sum(n > 0 for n in counts.values()),
          'maximum probability difference', worst, 'bytes', path.stat().st_size)
    print(model)


if __name__ == '__main__':
    main()
