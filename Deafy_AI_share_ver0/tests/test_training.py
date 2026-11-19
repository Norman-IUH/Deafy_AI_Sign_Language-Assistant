import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from step3_dataset import VSLDataset, split_manifest, stratified_split
from step4_model import GRUClassifier
from step5_train import fit, load_checkpoint, run_epoch
from step5_training_data import training_loaders, verify_manifest


class TrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'raw'
        for c, label in enumerate(('A', 'B')):
            folder = self.root / label
            folder.mkdir(parents=True)
            for i in range(3):
                length = 3 + i
                p = folder / f'{i}.npy'
                np.save(p, np.full((1, length, 126), 1 + c * 10 + i, dtype=np.float32))
                p.with_suffix('.json').write_text(json.dumps(dict(
                    label=label, signer='P01', session_id=label,
                    feature_order='Left then Right xyz', mirrored_before_inference=True,
                    coordinates='normalized', duration_seconds=2.0)))
        self.ds = VSLDataset(self.root)
        train, val = stratified_split(self.ds)
        self.manifest = split_manifest(self.ds, train, val, 42, 0.2)
        self.split = self.base / 'split.json'
        self.split.write_text(json.dumps(self.manifest))

    def test_manifest_rejects_tampering_overlap_missing_and_added(self):
        a, b = verify_manifest(self.ds, self.manifest)
        self.assertEqual((len(a), len(b)), (4, 2))
        for key, value in (('path', '../outside.npy'), ('sha256', 'bad'),
                           ('label', 99), ('source_length', 99), ('signer', 'P99')):
            altered = copy.deepcopy(self.manifest)
            altered['train'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_manifest(self.ds, altered)
        altered = copy.deepcopy(self.manifest)
        altered['validation'][0] = altered['train'][0]
        with self.assertRaises(ValueError):
            verify_manifest(self.ds, altered)
        altered = copy.deepcopy(self.manifest)
        altered['train'].pop()
        with self.assertRaises(ValueError):
            verify_manifest(self.ds, altered)
        altered = copy.deepcopy(self.manifest)
        altered['class_to_idx'] = {'A': 1, 'B': 0}
        with self.assertRaises(ValueError):
            verify_manifest(self.ds, altered)
        np.save(self.root / 'A' / 'new.npy', np.full((1, 4, 126), 100., np.float32))
        with self.assertRaises(ValueError):
            training_loaders(self.root, self.split)

    def test_modified_or_missing_file_rejected(self):
        p = self.root / 'A' / '0.npy'
        np.save(p, np.full((1, 3, 126), 70., np.float32))
        with self.assertRaisesRegex(ValueError, 'sha256'):
            training_loaders(self.root, self.split)
        p.unlink()
        with self.assertRaises(ValueError):
            training_loaders(self.root, self.split)

    def test_lengths_remain_aligned_under_shuffle(self):
        train, val, ds, manifest, preprocessing = training_loaders(self.root, self.split, batch_size=3)
        for loader in (train, val):
            for x, y, lengths in loader:
                for row, label, length in zip(x, y, lengths):
                    marker = int(row[0, 0])
                    expected = 3 + (marker - 1) % 10
                    self.assertEqual(int(length), expected)
                    self.assertEqual(int(label), (marker - 1) // 10)
                    self.assertFalse(row[length:].any())

    def test_weighted_metrics_and_validation_no_updates(self):
        class Fixed(torch.nn.Module):
            def forward(self, x, lengths):
                return x[:, 0, :3]
        x = torch.randn(5, 1, 3)
        y = torch.tensor([0, 1, 2, 1, 0])
        loader = DataLoader(TensorDataset(x, y, torch.ones(5, dtype=torch.long)), batch_size=3)
        result = run_epoch(Fixed(), loader, 'cpu')
        expected = torch.nn.functional.cross_entropy(x[:, 0], y).item()
        self.assertAlmostEqual(result['loss'], expected, places=6)
        self.assertAlmostEqual(result['accuracy'], (x[:, 0].argmax(1) == y).float().mean().item(), places=6)
        model = GRUClassifier(2, hidden_size=4, num_layers=1)
        train, val, *_ = training_loaders(self.root, self.split)
        original = {k: v.clone() for k, v in model.state_dict().items()}
        run_epoch(model, val, 'cpu')
        self.assertFalse(model.training)
        self.assertTrue(all(torch.equal(original[k], v) for k, v in model.state_dict().items()))
        run_epoch(model, train, 'cpu', torch.optim.Adam(model.parameters(), lr=0.01))
        self.assertTrue(any(not torch.equal(original[k], v) for k, v in model.state_dict().items()))

    def test_training_checkpoint_reload_and_raw_preservation(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        run, history = fit(self.root, self.split, self.base / 'run', epochs=2)
        model, checkpoint = load_checkpoint(run / 'best_model.pth')
        self.assertEqual(checkpoint['best_epoch'], min(history, key=lambda row: row['val_loss'])['epoch'])
        self.assertEqual(checkpoint['class_to_idx'], {'A': 0, 'B': 1})
        self.assertEqual(checkpoint['preprocessing']['sequence_length'], 30)
        self.assertEqual(model(torch.zeros(2, 30, 126), [5, 3]).shape, (2, 2))
        self.assertTrue(json.loads((run / 'summary.json').read_text())['reload_verified'])
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        checkpoint_hash = hashlib.sha256((run / 'best_model.pth').read_bytes()).hexdigest()
        with self.assertRaises(FileExistsError):
            fit(self.root, self.split, run, epochs=1)
        self.assertEqual(checkpoint_hash, hashlib.sha256((run / 'best_model.pth').read_bytes()).hexdigest())

    def test_lowest_loss_keeps_earliest_tie_not_final_epoch(self):
        def metrics(loss):
            return dict(loss=loss, accuracy=0.5, samples=2)
        # Train/val per epoch then validation after reload; epoch 2 wins, epoch 3 ties.
        results = [metrics(1), metrics(.8), metrics(1), metrics(.5), metrics(1), metrics(.5), metrics(.5)]
        with patch('step5_train.run_epoch', side_effect=results):
            run, history = fit(self.root, self.split, self.base / 'selection', epochs=3)
        _, checkpoint = load_checkpoint(run / 'best_model.pth')
        self.assertEqual(checkpoint['best_epoch'], 2)
        self.assertEqual(checkpoint['best_val_loss'], .5)


if __name__ == '__main__':
    unittest.main()
