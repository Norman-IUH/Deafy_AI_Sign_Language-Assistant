import unittest

import torch
from step4_model import GRUClassifier


class GRUTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)
        self.model = GRUClassifier(num_classes=3)

    def test_shapes_for_variable_batch_and_time(self):
        self.model.eval()
        with torch.no_grad():
            for batch, steps in ((4, 30), (1, 1), (2, 12), (7, 45)):
                with self.subTest(batch=batch, steps=steps):
                    out = self.model(torch.randn(batch, steps, 126))
                    self.assertEqual(out.shape, (batch, 3))
                    self.assertEqual(out.dtype, torch.float32)
                    self.assertTrue(torch.isfinite(out).all())

    def test_unsorted_lengths_match_individual_sequences_and_ignore_tail(self):
        self.model.eval()
        x = torch.randn(3, 12, 126)
        lengths = torch.tensor([7, 12, 3])  # Deliberately unsorted.
        changed = x.clone()
        for i, length in enumerate(lengths):
            changed[i, length:] = 100  # Different padding contents must not change logits.
        with torch.no_grad():
            actual = self.model(x, lengths)
            torch.testing.assert_close(actual, self.model(changed, lengths))
            for i, length in enumerate(lengths):
                torch.testing.assert_close(actual[i:i+1], self.model(x[i:i+1, :length]), atol=1e-6, rtol=1e-5)
            torch.testing.assert_close(self.model(x), self.model(x, [12, 12, 12]), atol=1e-6, rtol=1e-5)

    def test_logits_are_raw_and_hidden_state_not_reused(self):
        self.model.eval()
        with torch.no_grad():
            self.model.fc.weight.zero_()
            self.model.fc.bias.copy_(torch.tensor([-2., 0., 3.]))
            x = torch.randn(2, 30, 126)
            out = self.model(x)
            torch.testing.assert_close(out, torch.tensor([[-2., 0., 3.], [-2., 0., 3.]]))
            self.model(torch.randn_like(x))
            torch.testing.assert_close(out, self.model(x))

    def test_backward_reaches_all_layers(self):
        x = torch.randn(4, 10, 126, requires_grad=True)
        logits = self.model(x, [10, 6, 9, 3])
        # One gradient check only, no optimizer or parameter update.
        loss = torch.nn.functional.cross_entropy(logits, torch.tensor([0, 1, 2, 0]))
        loss.backward()
        self.assertTrue(torch.isfinite(x.grad).all())
        for name, parameter in self.model.named_parameters():
            with self.subTest(parameter=name):
                self.assertIsNotNone(parameter.grad)
                self.assertTrue(torch.isfinite(parameter.grad).all())
                self.assertGreater(parameter.grad.abs().sum().item(), 0)

    def test_invalid_input_and_lengths(self):
        for x in (torch.zeros(30, 126), torch.zeros(2, 30, 125), torch.zeros(0, 30, 126),
                  torch.zeros(2, 0, 126), torch.zeros(2, 30, 126, dtype=torch.long),
                  torch.full((2, 30, 126), float('nan'))):
            with self.subTest(shape=x.shape, dtype=x.dtype), self.assertRaises(ValueError):
                self.model(x)
        for lengths in ([0, 10], [31, 10], [2.5, 10.], [True, True], [10], [[10, 10]]):
            with self.subTest(lengths=lengths), self.assertRaises(ValueError):
                self.model(torch.zeros(2, 30, 126), lengths)

    def test_constructor_and_class_count(self):
        for config in ({'num_classes': 1}, {'num_classes': 3, 'hidden_size': 0},
                       {'num_classes': 3, 'num_layers': True}, {'num_classes': 3, 'input_size': -1}):
            with self.assertRaises(ValueError):
                GRUClassifier(**config)
        model = GRUClassifier(num_classes=5, num_layers=1)
        self.assertEqual(model(torch.zeros(2, 7, 126)).shape, (2, 5))


if __name__ == '__main__':
    unittest.main()
