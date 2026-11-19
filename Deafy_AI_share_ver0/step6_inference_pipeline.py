"""Timestamp-based inference and display-only decision gate, without camera I/O."""
from collections import deque
import math

import numpy as np
import torch
from step2_collect_data import required_visible, resample

FEATURE_ORDER = 'Left(landmark0.xyz..20.xyz),Right(landmark0.xyz..20.xyz)'
MOCK_MESSAGES = {'Bat_Den': 'LIGHT_ON (simulation)', 'Dong_Y': 'CHAT: Dong y',
                 'Tam_Biet': 'CHAT: Tam biet'}


def validate_preprocessing(checkpoint):
    prep = checkpoint.get('preprocessing', {})
    expected = dict(feature_order=FEATURE_ORDER, mirrored_before_inference=True,
                    sequence_length=30, input_size=126, duration_seconds=3.0,
                    coordinates='normalized image x,y; wrist-relative z (not meters)',
                    normalization='none', padding='zeros_at_end', truncation='first_frames')
    for key, value in expected.items():
        if prep.get(key) != value:
            raise ValueError(f'Unsupported/missing checkpoint preprocessing: {key}')
    mapping = checkpoint['class_to_idx']
    if not all(isinstance(label, str) and label for label in mapping):
        raise ValueError('Checkpoint class names must be nonempty strings')
    return prep


class TimeWindow:
    def __init__(self, required='right', duration=2.0, length=30, max_gap=0.2):
        if required not in ('right', 'left', 'both', 'either'):
            raise ValueError('Invalid required hands')
        self.required, self.duration, self.length, self.max_gap = required, duration, length, max_gap
        self.frames = deque()

    def clear(self):
        self.frames.clear()

    @property
    def coverage(self):
        return self.frames[-1][0] - self.frames[0][0] if len(self.frames) > 1 else 0.0

    def add(self, timestamp, features, mask):
        if not math.isfinite(timestamp) or np.shape(features) != (126,) or not np.isfinite(features).all():
            self.clear()
            raise ValueError('Invalid timestamp/features')
        if np.shape(mask) != (2,):
            self.clear()
            raise ValueError('Invalid hand presence mask')
        if not required_visible(mask, self.required):
            self.clear()
            return 'Required hand absent/uncertain; buffer reset'
        reason = ''
        if self.frames:
            delta = timestamp - self.frames[-1][0]
            if delta <= 0 or delta > self.max_gap:
                self.clear()
                reason = 'Camera timing gap; buffer reset'
        self.frames.append((timestamp, np.asarray(features, dtype=np.float32).copy(), np.asarray(mask).copy()))
        start = timestamp - self.duration
        # Keep one frame at/before the grid origin for nearest-neighbor coverage.
        while len(self.frames) > 1 and self.frames[1][0] <= start:
            self.frames.popleft()
        return reason

    def sample(self):
        if len(self.frames) < 2 or self.coverage < self.duration:
            return None
        start = self.frames[-1][0] - self.duration
        times, frames, masks = zip(*self.frames)
        relative = np.asarray(times) - start
        data, _, _, _ = resample(relative, frames, masks, self.duration, self.length, self.max_gap)
        return data  # Shape: (1,30,126), same time grid/feature order as collection.


class DecisionGate:
    def __init__(self, threshold=0.7, stable_count=3, cooldown=2.0):
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError('threshold must be in [0,1]')
        if not isinstance(stable_count, int) or isinstance(stable_count, bool) or stable_count < 1:
            raise ValueError('stable_count must be a positive integer')
        if not math.isfinite(cooldown) or cooldown < 0:
            raise ValueError('cooldown must be finite and nonnegative')
        self.threshold, self.stable_count, self.cooldown = threshold, stable_count, cooldown
        self.last_emit = float('-inf')
        self.reset()

    def reset(self):
        self.candidate, self.count, self.latched = None, 0, None
        # Preserve cooldown time across tracking loss/manual reset to avoid repeated events.

    def update(self, label, score, now):
        if not math.isfinite(score) or not math.isfinite(now) or not 0 <= score <= 1:
            self.reset()
            raise ValueError('Invalid prediction score/time')
        if score < self.threshold:
            self.candidate, self.count = None, 0
            return False, False
        self.count = self.count + 1 if self.candidate == label else 1
        self.candidate = label
        accepted = self.count >= self.stable_count
        emitted = accepted and self.latched != label and now - self.last_emit >= self.cooldown
        if emitted:
            self.last_emit, self.latched = now, label
        return accepted, emitted


def predict(model, sequence, class_to_idx):
    x = torch.from_numpy(np.asarray(sequence, dtype=np.float32))  # Shape: (1,T,126).
    with torch.inference_mode():
        logits = model(x)  # Shape: (1,num_classes).
        if logits.shape != (1, len(class_to_idx)) or not torch.isfinite(logits).all():
            raise ValueError('Invalid model logits')
        probabilities = logits.softmax(dim=1)[0]  # Shape: (num_classes,).
    index = int(probabilities.argmax())
    inverse = {value: key for key, value in class_to_idx.items()}
    return inverse[index], float(probabilities[index])
