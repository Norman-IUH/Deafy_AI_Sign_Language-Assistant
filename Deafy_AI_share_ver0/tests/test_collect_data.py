import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

import numpy as np
from step2_collect_data import extract_features, required_visible, resample, save_sample


def detection(label, value):
    return (NS(landmark=[NS(x=value, y=value, z=-value) for _ in range(21)]),
            NS(classification=[NS(label=label, score=0.99)]))


class CollectionTests(unittest.TestCase):
    def test_fixed_slots_even_when_detection_order_reversed(self):
        right, left = detection("Right", 0.8), detection("Left", 0.2)
        features, mask = extract_features(NS(multi_hand_landmarks=[right[0], left[0]],
                                            multi_handedness=[right[1], left[1]]))
        self.assertEqual(features.shape, (126,))
        self.assertEqual(features.dtype, np.float32)
        np.testing.assert_allclose(features[:3], [0.2, 0.2, -0.2])
        np.testing.assert_allclose(features[63:66], [0.8, 0.8, -0.8])
        self.assertTrue(mask.all())

    def test_missing_and_duplicate_not_stale(self):
        hand, side = detection("Left", 0.3)
        f, mask = extract_features(NS(multi_hand_landmarks=[hand], multi_handedness=[side]))
        self.assertTrue(required_visible(mask, "left"))
        self.assertFalse(required_visible(mask, "both"))
        self.assertFalse(f[63:].any())
        f, mask = extract_features(NS(multi_hand_landmarks=[hand, hand], multi_handedness=[side, side]))
        self.assertFalse(mask.any())
        self.assertFalse(f.any())
        f, mask = extract_features(NS(multi_hand_landmarks=None, multi_handedness=None))
        self.assertFalse(f.any())

    def test_regular_sampling_shape_and_saved_roundtrip(self):
        times = np.linspace(0, 2, 61)
        frames = np.repeat(times[:, None], 126, axis=1)
        masks = np.ones((61, 2), dtype=bool)
        data, sampled, grid, indices = resample(times, frames, masks, 2, 30)
        self.assertEqual(data.shape, (1, 30, 126))
        self.assertEqual(data.dtype, np.float32)
        np.testing.assert_allclose(data[0, :, 0], grid, atol=1e-6)
        self.assertEqual(sampled.shape, (30, 2))
        with tempfile.TemporaryDirectory() as tmp:
            first = save_sample(Path(tmp), data, {"label": "Bat_Den"})
            second = save_sample(Path(tmp), data, {"label": "Bat_Den"})
            self.assertNotEqual(first, second)
            np.testing.assert_array_equal(np.load(first, allow_pickle=False), data)
            self.assertEqual(json.loads(first.with_suffix('.json').read_text())["label"], "Bat_Den")

    def test_camera_gap_rejected(self):
        with self.assertRaises(ValueError):
            resample([0, 0.1, 1.5, 2], np.zeros((4, 126)), np.ones((4, 2)), 2, 30)

    def test_nonfinite_save_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_sample(Path(tmp), np.full((1, 30, 126), np.nan), {})
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
