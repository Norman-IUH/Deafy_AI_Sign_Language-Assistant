import json
from pathlib import Path
import tempfile
import unittest
import warnings

import numpy as np
import torch
from step3_dataset import VSLDataset, create_dataloaders, stratified_split


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def save(self, label, name, length=30, value=1):
        folder = self.root / label
        folder.mkdir(exist_ok=True)
        path = folder / f"{name}.npy"
        np.save(path, np.full((1, length, 126), value, np.float32))
        return path

    def populate(self):
        for j, (label, count) in enumerate((("Bat_Den", 10), ("Dong_Y", 5), ("Tam_Biet", 5))):
            for i in range(count):
                self.save(label, str(i), value=1 + 100 * j + i)

    def test_padding_and_truncation_preserve_order(self):
        short = self.save("A", "short", length=3)
        long = self.save("A", "long", length=40)
        values = np.repeat(np.arange(40, dtype=np.float32)[:, None], 126, axis=1)
        np.save(long, values[None])
        original = short.read_bytes()
        ds = VSLDataset(self.root)
        for i, sample in enumerate(ds.samples):
            x, y = ds[i]
            self.assertEqual(tuple(x.shape), (30, 126))
            self.assertEqual(x.dtype, torch.float32)
            self.assertEqual(y.dtype, torch.long)
            self.assertEqual(y.ndim, 0)
            if sample.path == short:
                self.assertTrue(torch.equal(x[:3], torch.ones(3, 126)))
                self.assertEqual(torch.count_nonzero(x[3:]).item(), 0)
            else:
                self.assertTrue(torch.equal(x[:, 0], torch.arange(30, dtype=torch.float32)))
        self.assertEqual(short.read_bytes(), original)

    def test_split_reproducible_disjoint_stratified(self):
        self.populate()
        ds = VSLDataset(self.root)
        self.assertEqual(ds.class_to_idx, {"Bat_Den": 0, "Dong_Y": 1, "Tam_Biet": 2})
        train, val = stratified_split(ds)
        self.assertEqual((len(train), len(val)), (16, 4))
        self.assertEqual((train, val), stratified_split(ds))
        self.assertFalse(set(train) & set(val))
        self.assertEqual(set(train) | set(val), set(range(20)))
        self.assertEqual([sum(ds.samples[i].label == c for i in val) for c in range(3)], [2, 1, 1])

    def test_all_batches_no_dropped_tail_seeded_order(self):
        self.populate()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            train, val, _ = create_dataloaders(self.root, batch_size=6)
            train2, _, _ = create_dataloaders(self.root, batch_size=6)
        batches = list(train)
        self.assertEqual([len(y) for x, y in batches], [6, 6, 4])
        self.assertEqual(sum(len(y) for x, y in val), 4)
        self.assertTrue(torch.equal(torch.cat([x for x, y in batches]),
                                    torch.cat([x for x, y in train2])))

    def test_invalid_arrays_fail_with_filename(self):
        p = self.save('A', 'bad')
        for a in (np.zeros((30, 126)), np.zeros((2, 30, 126)), np.zeros((1, 0, 126)),
                  np.zeros((1, 30, 125)), np.full((1, 30, 126), np.nan),
                  np.full((1, 30, 126), np.inf), np.full((1, 30, 126), 'oops')):
            with self.subTest(shape=a.shape, dtype=a.dtype):
                np.save(p, a)
                with self.assertRaisesRegex(ValueError, 'bad.npy'):
                    VSLDataset(self.root)

    def test_metadata_mismatch_and_duplicate_rejected(self):
        p = self.save('A', 'one')
        p.with_suffix('.json').write_text(json.dumps({'label': 'B'}))
        with self.assertRaisesRegex(ValueError, 'metadata'):
            VSLDataset(self.root)
        p.with_suffix('.json').write_text(json.dumps({'label': 'A'}))
        self.save('B', 'copy')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            VSLDataset(self.root)

    def test_empty_and_insufficient_data(self):
        with self.assertRaisesRegex(ValueError, 'No label'):
            VSLDataset(self.root)
        self.save('A', 'one')
        self.save('B', 'one', value=2)
        with self.assertRaisesRegex(ValueError, 'at least 2'):
            stratified_split(VSLDataset(self.root))

    def test_invalid_configuration(self):
        self.populate()
        for length in (0, -1):
            with self.assertRaises(ValueError):
                VSLDataset(self.root, length)
        ds = VSLDataset(self.root)
        for ratio in (0, 1, float('nan')):
            with self.assertRaises(ValueError):
                stratified_split(ds, ratio)
        with self.assertRaises(ValueError):
            create_dataloaders(self.root, batch_size=0)


if __name__ == '__main__':
    unittest.main()
