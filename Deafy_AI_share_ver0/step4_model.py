"""Step 4: GRU classifier for hand-landmark sequences."""
import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence


class GRUClassifier(nn.Module):
    def __init__(self, num_classes, input_size=126, hidden_size=64, num_layers=2):
        super().__init__()
        for name, value in (("num_classes", num_classes), ("input_size", input_size),
                            ("hidden_size", hidden_size), ("num_layers", num_layers)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if num_classes < 2:
            raise ValueError("num_classes must be at least 2")
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.num_classes = num_classes
        self.gru = nn.GRU(input_size=input_size, hidden_size=hidden_size,
                          num_layers=num_layers, batch_first=True, bidirectional=False)
        self.fc = nn.Linear(hidden_size, num_classes)

    def forward(self, x, lengths=None):
        # X shape: (Batch_size, Sequence_length, Input_size=126).
        if not isinstance(x, torch.Tensor) or x.ndim != 3:
            raise ValueError("x must be a Tensor of shape (B, T, input_size)")
        batch_size, steps, features = x.shape
        if batch_size < 1 or steps < 1 or features != self.input_size:
            raise ValueError(f"x needs B>0, T>0 and input_size={self.input_size}; got {tuple(x.shape)}")
        if x.dtype != self.fc.weight.dtype or x.device != self.fc.weight.device:
            raise ValueError("x must have the same floating dtype and device as the model")
        if not torch.isfinite(x).all():
            raise ValueError("x contains NaN/Inf")
        inputs = x
        if lengths is not None:
            lengths = torch.as_tensor(lengths)
            if lengths.ndim != 1 or lengths.shape[0] != batch_size:
                raise ValueError("lengths must have shape (B,)")
            if lengths.dtype not in (torch.int8, torch.int16, torch.int32, torch.int64, torch.uint8):
                raise ValueError("lengths must contain integers")
            if torch.any(lengths < 1) or torch.any(lengths > steps):
                raise ValueError("Each valid length must satisfy 1 <= length <= T")
            # Lengths shape: (Batch_size,); CPU int64 required by packing.
            valid_lengths = lengths.detach().to(device="cpu", dtype=torch.int64)
            inputs = pack_padded_sequence(x, valid_lengths, batch_first=True, enforce_sorted=False)
        # Without packing: output shape (B, T, hidden_size).
        # h_n shape: (num_layers, B, hidden_size), also when packing.
        # Omitting h_0 initializes zeros per call; batches do not share hidden state.
        _, h_n = self.gru(inputs)
        last_hidden = h_n[-1]  # Shape: (B, hidden_size); last VALID frame if lengths supplied.
        logits = self.fc(last_hidden)  # Shape: (B, num_classes).
        # Return raw logits. CrossEntropyLoss in Step 5 will apply log-softmax internally.
        return logits
