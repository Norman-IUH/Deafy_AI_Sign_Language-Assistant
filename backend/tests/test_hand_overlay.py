import numpy as np

from recognition_service import CameraService, draw_hand_overlay


def test_optional_overlay_keeps_original_camera_pixels(tmp_path):
    import cv2
    service = CameraService(tmp_path)
    original = np.zeros((100, 200, 3), dtype=np.uint8)
    hand = [[.25, .5]] * 21
    service.frame_image = original
    service.frame_hands = [hand]
    service.jpeg = cv2.imencode('.jpg', original)[1].tobytes()
    assert service.frame() == service.jpeg
    annotated = cv2.imdecode(np.frombuffer(service.frame(True), np.uint8), cv2.IMREAD_COLOR)
    assert annotated[50, 50].any()
    assert not annotated[50, 150].any()
    assert not original.any()
    assert service.frame() == service.jpeg
    service.stop()
    assert service.frame(True) is None


def test_empty_or_invalid_landmarks_draw_nothing():
    original = np.zeros((100, 200, 3), dtype=np.uint8)
    assert not draw_hand_overlay(original.copy(), []).any()
    assert not draw_hand_overlay(original.copy(), [[[float('nan'), .5]] * 21]).any()
