"""Explicit local experiment profiles. Production loaders/defaults stay unchanged."""
import hashlib
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'old': {'name': 'Model cũ · 25 ký hiệu',
            'path': 'Deafy_AI_share_ver0/artifacts/step5/run_20261026T045637Z_ebe324f6/best_model.pth',
            'sha256': '232f4cb16dc7caeef355ab7b976581a39a93e039b8b7f88afd091add8b9f0f15'},
    'new': {'name': 'artifacts_2 · 22 ký hiệu',
            'path': 'artifacts_2/artifacts/step5/run_20261105T050614Z_2211739e/best_model.pth',
            'sha256': '031d470cfd8d3c734c441da35b090cb91ddb197a84d9fb8391ce4ae16adc40f6'},
}


def checkpoint_path(profile):
    if profile not in PROFILES:
        raise ValueError('Chọn model old hoặc new.')
    info = PROFILES[profile]
    path = ROOT / info['path']
    if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
        raise ValueError('Checkpoint đã đổi SHA256. Cần kiểm tra lại trước khi thử.')
    return path


@lru_cache(maxsize=1)
def model_schemas():
    import torch
    result = {}
    for name in PROFILES:
        checkpoint = torch.load(checkpoint_path(name), map_location='cpu', weights_only=True)
        mapping = checkpoint['class_to_idx']
        if sorted(mapping.values()) != list(range(len(mapping))) or len(mapping) != checkpoint['model_config']['num_classes']:
            raise ValueError('Invalid model class mapping')
        result[name] = {'classes': mapping, 'preprocessing': checkpoint['preprocessing'],
                        'training_subjects': sorted({r['signer'] for r in checkpoint['split_provenance']['manifest']['train'] if r.get('signer')})}
    if result['old']['preprocessing'] != result['new']['preprocessing']:
        raise ValueError('Hai model khác preprocessing; chưa cho thu tập so sánh chung.')
    return result
