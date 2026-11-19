"""Kiểm tra các nhánh lỗi bằng mock; không truy cập webcam thật."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import numpy as np
import step1_test_mediapipe as app
class SandboxTests(unittest.TestCase):
    def test_no_hands(self):
        self.assertEqual(app.index_tips(NS(multi_hand_landmarks=None, multi_handedness=None)), [])

    def test_two_hands_index_tip(self):
        hand = NS(landmark=[NS(x=i / 21, y=0.5, z=-i / 21) for i in range(21)])
        result = NS(multi_hand_landmarks=[hand, hand], multi_handedness=[
            NS(classification=[NS(label="Left")]), NS(classification=[NS(label="Right")])])
        self.assertEqual(app.index_tips(result), [
            ("Left", 8 / 21, 0.5, -8 / 21), ("Right", 8 / 21, 0.5, -8 / 21)])

    def exercise(self, opened=True, read_ok=False, process_error=False):
        cap = MagicMock()
        cap.isOpened.return_value = opened
        cap.read.return_value = (read_ok, np.zeros((48, 64, 3), dtype=np.uint8) if read_ok else None)
        with patch.object(app.cv2, "VideoCapture", return_value=cap), \
             patch.object(app.cv2, "destroyAllWindows") as cleanup, \
             patch.object(app.cv2, "namedWindow"), \
             patch.object(app.cv2, "imshow"), \
             patch.object(app.cv2, "waitKey", return_value=ord("q") if read_ok else -1), \
             patch.object(app.mp.solutions.hands, "Hands") as factory:
            hands = factory.return_value.__enter__.return_value
            hands.process.return_value = NS(multi_hand_landmarks=None, multi_handedness=None)
            if process_error:
                hands.process.side_effect = RuntimeError("Inference failed")
            if not opened or not read_ok or process_error:
                with self.assertRaises(RuntimeError):
                    app.run()
            else:
                app.run()
            cap.release.assert_called_once()
            cleanup.assert_called_once()
            if opened:
                factory.return_value.__exit__.assert_called_once()
            if opened and not read_ok:
                self.assertEqual(cap.read.call_count, 10)

    def test_open_failure_cleanup(self):
        self.exercise(opened=False)

    def test_read_failure_cleanup(self):
        self.exercise()

    def test_inference_failure_cleanup(self):
        self.exercise(read_ok=True, process_error=True)

    def test_no_hand_frame_and_quit_cleanup(self):
        self.exercise(read_ok=True)


if __name__ == "__main__":
    unittest.main()
