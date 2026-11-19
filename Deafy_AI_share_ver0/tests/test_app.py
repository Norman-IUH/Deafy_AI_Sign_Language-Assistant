import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import torch
import step6_app as app
from step6_inference_pipeline import FEATURE_ORDER
from step4_model import GRUClassifier


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoint = Path(self.temp.name) / 'model.pth'
        self.model = GRUClassifier(3)
        self.payload = dict(schema_version=1, model_config=dict(num_classes=3, input_size=126, hidden_size=64, num_layers=2),
                            model_state_dict=self.model.state_dict(), class_to_idx={'Bat_Den': 0, 'Dong_Y': 1, 'Tam_Biet': 2},
                            best_epoch=3, best_val_accuracy=.5,
                            preprocessing=dict(feature_order=FEATURE_ORDER, mirrored_before_inference=True,
                                               sequence_length=30, input_size=126, duration_seconds=3.0,
                                               coordinates='normalized image x,y; wrist-relative z (not meters)',
                                               normalization='none', padding='zeros_at_end', truncation='first_frames'))
        torch.save(self.payload, self.checkpoint)
        self.args = NS(required_hands='right', threshold=.7, stable_count=3, cooldown=2,
                       backend='auto', camera=0, interval=.2)

    def test_check_only_never_opens_camera_or_hands(self):
        with patch('sys.argv', ['step6_app.py', '--checkpoint', str(self.checkpoint), '--check-only']), \
             patch.object(app.cv2, 'VideoCapture', side_effect=AssertionError('Camera opened')), \
             patch.object(app.mp.solutions.hands, 'Hands', side_effect=AssertionError('Hands opened')):
            self.assertEqual(app.main(), 0)

    def test_missing_or_incompatible_checkpoint_before_camera(self):
        bad = copy.deepcopy(self.payload)
        bad['preprocessing']['mirrored_before_inference'] = False
        torch.save(bad, self.checkpoint)
        with patch.object(app.cv2, 'VideoCapture') as camera:
            with self.assertRaises(ValueError):
                app.check_model(self.checkpoint)
            with self.assertRaises(OSError):
                app.check_model(self.checkpoint.with_name('missing.pth'))
            camera.assert_not_called()

    def test_rejects_window_different_from_training_before_camera(self):
        bad = copy.deepcopy(self.payload)
        bad['preprocessing']['duration_seconds'] = 2.0
        torch.save(bad, self.checkpoint)
        with patch.object(app.cv2, 'VideoCapture') as camera:
            with self.assertRaisesRegex(ValueError, 'duration_seconds'):
                app.check_model(self.checkpoint)
            camera.assert_not_called()

    def exercise(self, opened=True, failure=False, inference_error=False):
        cap = MagicMock()
        cap.isOpened.return_value = opened
        cap.read.return_value = (False, None) if failure else (True, np.zeros((48, 64, 3), np.uint8))
        with patch.object(app.cv2, 'VideoCapture', return_value=cap), \
             patch.object(app.cv2, 'namedWindow'), patch.object(app.cv2, 'imshow'), \
             patch.object(app.cv2, 'destroyAllWindows') as cleanup, \
             patch.object(app.cv2, 'waitKey', return_value=-1 if failure else ord('q')), \
             patch.object(app.mp.solutions.hands, 'Hands') as factory, \
             patch.object(app, 'predict') as predict:
            hands = factory.return_value.__enter__.return_value
            hands.process.return_value = NS(multi_hand_landmarks=None, multi_handedness=None)
            if inference_error:
                hands.process.side_effect = RuntimeError('MediaPipe failed')
            if not opened or failure or inference_error:
                with self.assertRaises(RuntimeError):
                    app.run_camera(self.args, self.model, self.payload)
            else:
                app.run_camera(self.args, self.model, self.payload)
            cap.release.assert_called_once()
            cleanup.assert_called_once()
            predict.assert_not_called()  # Neither empty nor absent-hand frames reach GRU.
            if failure:
                self.assertEqual(cap.read.call_count, 10)

    def test_camera_open_failure_cleanup(self):
        self.exercise(opened=False)

    def test_camera_read_failure_cleanup(self):
        self.exercise(failure=True)

    def test_mediapipe_error_cleanup(self):
        self.exercise(inference_error=True)

    def test_no_hand_and_quit_cleanup(self):
        self.exercise()

    def test_display_event_respects_cooldown_and_latch(self):
        gate = app.DecisionGate(threshold=.7, stable_count=1, cooldown=2)
        accepted, emitted = gate.update('Bat_Den', .9, 0)
        self.assertEqual(app.mock_display('Bat_Den', accepted, emitted), 'LIGHT_ON (simulation)')
        accepted, emitted = gate.update('Bat_Den', .9, 3)
        self.assertIn('suppresses new event', app.mock_display('Bat_Den', accepted, emitted))
        self.assertFalse(emitted)  # Same label already latched, despite elapsed cooldown.
        accepted, emitted = gate.update('Dong_Y', .9, 3.1)
        self.assertEqual(app.mock_display('Dong_Y', accepted, emitted), 'CHAT: Dong y')
        accepted, emitted = gate.update('Tam_Biet', .9, 3.2)
        self.assertTrue(accepted)
        self.assertFalse(emitted)  # New stable label is blocked by cooldown.
        self.assertIn('suppresses new event', app.mock_display('Tam_Biet', accepted, emitted))
        gate.reset()
        accepted, emitted = gate.update('Tam_Biet', .1, 6)
        self.assertEqual(app.mock_display('Tam_Biet', accepted, emitted), 'NONE')
