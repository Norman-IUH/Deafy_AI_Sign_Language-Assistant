from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from landmark_recognition import TemplateModel, LandmarkRecognizer, feature_from_result


def test_template_rejects_unknown_and_empty_sequences(tmp_path):
    a, b = np.full((30, 126), .2), np.full((30, 126), .8)
    model = TemplateModel([a, b], [0, 1], ['Xin_Chao', 'Dong_Y'], [.03, .03])
    assert model.predict(a)['label'] == 'Xin_Chao'
    assert model.predict(a)['accepted']
    assert not model.predict(np.full((30, 126), .5))['accepted']
    assert not model.predict(np.zeros((30, 126)))['accepted']
    with pytest.raises(ValueError):
        model.predict(np.zeros((30, 96)))
    with pytest.raises(ValueError):
        model.predict(np.full((30, 126), np.nan))


def test_handedness_order_threshold_and_missing_hand():
    def detection(label, score, value):
        hand = SimpleNamespace(landmark=[SimpleNamespace(x=value, y=value, z=value) for _ in range(21)])
        category = SimpleNamespace(classification=[SimpleNamespace(label=label, score=score)])
        return hand, category
    right, right_class = detection('Right', .9, .8)
    left, left_class = detection('Left', .6, .2)
    feature = feature_from_result(SimpleNamespace(multi_hand_landmarks=[right, left],
                                                 multi_handedness=[right_class, left_class]))
    assert np.all(feature[:63] == 0)
    assert np.allclose(feature[63:], .8)


def test_live_window_requires_stability_resets_and_deduplicates():
    recognizer = LandmarkRecognizer.__new__(LandmarkRecognizer)
    a, b = np.full((30, 126), .2), np.full((30, 126), .8)
    recognizer.model = TemplateModel([a, b], [0, 1], ['Xin_Chao', 'Dong_Y'], [.03, .03])
    recognizer.history = deque(maxlen=240)
    recognizer.recent = deque(maxlen=2)
    recognizer.last_predict = float('-inf')
    recognizer.last_accepted = recognizer.no_hand_since = None
    recognizer.result = recognizer._state('collecting', '')
    results = [recognizer.push(a[0], i / 20) for i in range(91)]
    assert results[20]['status'] == 'collecting'
    assert sum(r['new_result'] for r in results) == 1
    assert results[-1]['label'] == 'xin_chao'
    assert results[-1]['text'] == 'Xin chào'
    recognizer.push(np.zeros(126), 4.6)
    assert recognizer.push(np.zeros(126), 5.2)['status'] == 'no_hands'
    assert recognizer.last_accepted is None
    results = [recognizer.push(a[0], 5.3 + i / 20) for i in range(91)]
    assert sum(r['new_result'] for r in results) == 1


def test_saved_model_and_camera_adapter(tmp_path):
    from pathlib import Path
    from shutil import copy2
    from recognition_service import CameraService
    root = Path(__file__).resolve().parents[1]
    if not (root / 'data/landmark_templates.npz').exists():
        pytest.skip('Run train_landmarks.py for supplied recordings first')
    (tmp_path / 'data').mkdir()
    copy2(root / 'data/landmark_templates.npz', tmp_path / 'data/landmark_templates.npz')
    service = CameraService(tmp_path)
    assert service.ai_status()['model_present']
    assert not service.ai_status()['ready']
    detector, recognizer = service._load_recognizer()
    try:
        assert detector is None
        assert len(recognizer.model.labels) == 25
        assert service.ai_status()['ready']
        assert recognizer.process(np.zeros((480, 640, 3), np.uint8), 0)['status'] == 'no_hands'
    finally:
        recognizer.close()
