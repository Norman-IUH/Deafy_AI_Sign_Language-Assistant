from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('torch')
from deafy_recognition import DeafyRecognizer
from recognition_service import CameraService


def test_configured_model2_uses_own_mapping_and_checksum(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.setenv('DAKT_GRU_CHECKPOINT','artifacts_2/artifacts/step5/run_20261105T050614Z_2211739e/best_model.pth')
    monkeypatch.setenv('DAKT_GRU_SHA256','031d470cfd8d3c734c441da35b090cb91ddb197a84d9fb8391ce4ae16adc40f6')
    monkeypatch.setenv('DAKT_GRU_NAME','Model 2')
    service=CameraService(root)
    assert service.ai_status()['model'] is None
    _,recognizer=service._load_recognizer()
    try:
        info=service.ai_status()
        assert info['ready'] and info['model']['num_classes']==22 and info['model']['classes']['Xin_Chao']==21
        assert 'Model 2' in info['pipeline'] and 'Goi' not in recognizer.labels
        result=recognizer.process(np.zeros((480,640,3),np.uint8),0)
        assert result['status']=='no_hands' and not result['new_result']
    finally:recognizer.close()
    monkeypatch.setenv('DAKT_GRU_SHA256','0'*64)
    with pytest.raises(ValueError,match='Checksum'):CameraService(root)._load_recognizer()
    monkeypatch.setenv('DAKT_GRU_CHECKPOINT','missing-checkpoint.pth')
    with pytest.raises(ValueError,match='Không tìm thấy'):CameraService(root)._load_recognizer()


def test_supplied_checkpoint_loads_and_blank_camera_does_not_emit():
    service = CameraService(Path(__file__).resolve().parents[1])
    if not service.deafy_checkpoint.is_file():
        pytest.skip('Supplied Deafy checkpoint not installed')
    assert 'Deafy' in service.ai_status()['pipeline']
    detector, recognizer = service._load_recognizer()
    try:
        assert detector is None
        assert service.ai_status()['ready']
        assert len(recognizer.labels) == 25
        assert recognizer.window.duration == 3.0
        assert recognizer.window.length == 30
        result = recognizer.process(np.zeros((480, 640, 3), np.uint8), 0)
        assert result['status'] == 'no_hands'
        assert not result['new_result'] and result['label'] is None
    finally:
        recognizer.close()


def test_live_gate_requires_full_window_stability_and_suppresses_repeats(monkeypatch):
    from step6_inference_pipeline import DecisionGate, TimeWindow
    recognizer = DeafyRecognizer.__new__(DeafyRecognizer)
    recognizer.window = TimeWindow(required='right', duration=3.0)
    recognizer.gate = DecisionGate(.7, 3, 2.0)
    recognizer.last_predict = float('-inf')
    recognizer.last_candidate = float('-inf')
    recognizer.candidate_label, recognizer.candidate_count = None, 0
    recognizer.result = recognizer._state('collecting', '')
    import torch
    recognizer.labels = {'Dong_Y': 0, 'Xin_Chao': 1, 'Cha': 2, 'Me': 3, 'Mo': 4}
    recognizer.model = lambda batch: torch.tensor([[5.,0.,0.,0.,0.]])
    features, mask = np.ones(126, np.float32), np.array([False, True])
    results = [recognizer.push(features, mask, i / 20) for i in range(101)]
    assert all(not r['new_result'] for r in results[:60])
    assert results[24]['elapsed_seconds'] == 1.2
    assert results[24]['window_seconds'] == 3.0
    assert results[-1]['elapsed_seconds'] == 3.0
    assert sum(r['new_result'] for r in results) == 1
    assert results[-1]['text'] == 'Đồng ý'
    assert results[-1]['label'] == 'dong_y'
    empty = recognizer.push(np.zeros(126), np.array([False, False]), 5.1)
    assert empty['status'] == 'no_hands' and not empty['new_result']
    assert empty['elapsed_seconds'] == 0
    results = [recognizer.push(features, mask, 5.2 + i / 20) for i in range(101)]
    assert sum(r['new_result'] for r in results) == 1
    gap = recognizer.push(features, mask, 11)
    assert gap['status'] == 'collecting' and not gap['new_result']
    assert gap['elapsed_seconds'] == 0
    recognizer.model = lambda batch: torch.zeros((1, 5))
    results = [recognizer.push(features, mask, 11.05 + i / 20) for i in range(101)]
    assert not any(r['new_result'] for r in results)
    assert results[-1]['status'] == 'uncertain'
    assert len(results[-1]['top_candidates']) == 3
    assert any(r.get('new_candidate') for r in results)


def test_preview_landmarks_are_unmirrored_without_changing_model_features():
    from types import SimpleNamespace
    recognizer = DeafyRecognizer.__new__(DeafyRecognizer)
    result = SimpleNamespace(
        multi_hand_landmarks=[SimpleNamespace(landmark=[SimpleNamespace(x=.2, y=.4, z=0) for _ in range(21)])],
        multi_handedness=[SimpleNamespace(classification=[SimpleNamespace(label='Right', score=.9)])])
    recognizer.hands = SimpleNamespace(process=lambda image: result)
    captured = []
    recognizer.push = lambda features, mask, now: captured.append(features) or {'new_result': False}
    recognizer.process(np.zeros((100, 200, 3), np.uint8), 0)
    assert np.isclose(recognizer.overlay_hands[0][0][0], .8)
    assert np.isclose(captured[0][63], .2)
