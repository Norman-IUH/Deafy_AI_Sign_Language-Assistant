import unittest
import numpy as np
import torch
from step2_collect_data import resample
from step6_inference_pipeline import DecisionGate, TimeWindow, predict, validate_preprocessing


class InferenceTests(unittest.TestCase):
    def test_window_uses_time_not_frame_count_and_matches_collection(self):
        window = TimeWindow()
        timestamps = np.linspace(0, 2, 61)
        frames = [np.full(126, t, np.float32) for t in timestamps]
        for i, (t, frame) in enumerate(zip(timestamps, frames)):
            window.add(t, frame, [False, True])
            if i == 30:
                self.assertIsNone(window.sample())  # 31 camera frames span only 1 second.
        actual = window.sample()
        expected, *_ = resample(timestamps, frames, [[False, True]] * 61, 2, 30)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(actual.shape, (1, 30, 126))
        for t in np.linspace(2.03, 4.03, 61):
            window.add(t, np.full(126, t, np.float32), [False, True])
        self.assertLess(len(window.frames), 70)
        self.assertIsNotNone(window.sample())

    def test_tracking_loss_gap_and_nonmonotonic_reset(self):
        w = TimeWindow()
        f = np.ones(126, np.float32)
        w.add(0, f, [False, True])
        self.assertIn('absent', w.add(.1, f, [False, False]))
        self.assertEqual(len(w.frames), 0)
        w.add(.2, f, [False, True])
        self.assertIn('gap', w.add(.5, f, [False, True]))
        self.assertEqual(len(w.frames), 1)
        self.assertIsNone(w.sample())
        self.assertIn('gap', w.add(.4, f, [False, True]))
        with self.assertRaises(ValueError):
            w.add(.6, np.full(126, np.nan), [False, True])
        self.assertEqual(len(w.frames), 0)

    def test_gate_threshold_stability_latch_cooldown_and_reset(self):
        gate = DecisionGate(.7, 2, 2)
        self.assertEqual(gate.update('A', .6, 0), (False, False))
        self.assertEqual(gate.update('A', .9, 1), (False, False))
        self.assertEqual(gate.update('A', .9, 1.2), (True, True))
        self.assertEqual(gate.update('A', .9, 5), (True, False))  # No repeated same-label event.
        self.assertEqual(gate.update('B', .9, 5.2), (False, False))
        self.assertEqual(gate.update('B', .9, 5.4), (True, True))
        gate.reset()
        self.assertEqual(gate.update('B', .9, 5.5), (False, False))
        self.assertEqual(gate.update('B', .9, 5.6), (True, False))  # Cooldown survives reset.
        self.assertEqual(gate.update('B', .9, 8), (True, True))
        self.assertEqual(gate.update('B', .1, 8.1), (False, False))
        self.assertEqual(gate.count, 0)

    def test_predict_mapping_from_checkpoint_not_alphabet(self):
        class Dummy(torch.nn.Module):
            def forward(self, x):
                self.shape = tuple(x.shape)
                return torch.tensor([[1., 3., -2.]])
        model = Dummy()
        label, score = predict(model, np.zeros((1, 30, 126), np.float32), {'Z': 0, 'A': 2, 'B': 1})
        self.assertEqual(label, 'B')
        self.assertEqual(model.shape, (1, 30, 126))
        self.assertTrue(.8 < score < 1)

    def test_invalid_threshold_and_missing_metadata(self):
        for kwargs in ({'threshold': float('nan')}, {'threshold': 2}, {'stable_count': 0}, {'cooldown': -1}):
            with self.assertRaises(ValueError):
                DecisionGate(**kwargs)
        with self.assertRaises(ValueError):
            validate_preprocessing({'class_to_idx': {'A': 0, 'B': 1}})
