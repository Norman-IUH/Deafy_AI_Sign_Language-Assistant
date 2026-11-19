"""Local template baseline for the supplied MediaPipe (30, 126) recordings."""
from collections import deque

import numpy as np

FEATURE_ORDER = 'Left(landmark0.xyz..20.xyz),Right(landmark0.xyz..20.xyz)'
from sign_vocabulary import LABEL_TEXT


def checked_sequence(sequence):
    sequence = np.asarray(sequence, dtype=np.float32)
    if sequence.shape != (30, 126) or not np.isfinite(sequence).all():
        raise ValueError('Mẫu MediaPipe cần có shape (30, 126) và giá trị hữu hạn.')
    return sequence


class TemplateModel:
    def __init__(self, samples, targets, labels, radii):
        self.samples = np.stack([checked_sequence(s) for s in samples])
        self.targets = np.asarray(targets, dtype=np.int64)
        self.labels = list(labels)
        self.radii = np.asarray(radii, dtype=np.float32)
        if (self.targets.shape != (len(self.samples),) or not self.labels
                or len(set(self.labels)) != len(self.labels)
                or self.radii.shape != (len(self.labels),)
                or not np.isfinite(self.radii).all() or np.any(self.radii <= 0)
                or set(self.targets) != set(range(len(self.labels)))):
            raise ValueError('Model MediaPipe có nhãn hoặc ngưỡng không hợp lệ.')

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            if int(data['schema_version']) != 1 or str(data['feature_order']) != FEATURE_ORDER:
                raise ValueError('Model MediaPipe không đúng định dạng.')
            return cls(data['samples'], data['targets'], data['labels'].tolist(), data['radii'])

    def predict(self, sequence):
        distances = np.sqrt(np.mean((self.samples - checked_sequence(sequence)) ** 2, axis=(1, 2)))
        scores = np.array([np.min(distances[self.targets == i]) for i in range(len(self.labels))])
        order = np.argsort(scores)
        best = int(order[0])
        distance = float(scores[best])
        margin = 1.0 - distance / max(float(scores[order[1]]), 1e-8) if len(order) > 1 else 1.0
        accepted = bool(np.any(sequence) and distance <= self.radii[best] and margin >= .12)
        # This is template similarity, not a calibrated probability of correctness.
        similarity = float(1 / (1 + (distance / self.radii[best]) ** 2))
        return {'label': self.labels[best], 'confidence': similarity, 'accepted': accepted,
                'distance': distance, 'margin': margin}


def feature_from_result(result):
    feature = np.zeros((2, 21, 3), dtype=np.float32)
    scores = [0.7, 0.7]
    for hand, handedness in zip(result.multi_hand_landmarks or [], result.multi_handedness or []):
        category = handedness.classification[0]
        slot = {'Left': 0, 'Right': 1}.get(category.label)
        if slot is not None and category.score >= scores[slot]:
            feature[slot] = [[point.x, point.y, point.z] for point in hand.landmark]
            scores[slot] = category.score
    return feature.reshape(126)


class LandmarkRecognizer:
    def __init__(self, path):
        import mediapipe as mp
        self.model = TemplateModel.load(path)
        self.hands = mp.solutions.hands.Hands(
            max_num_hands=2, model_complexity=1,
            min_detection_confidence=.5, min_tracking_confidence=.5)
        self.history = deque(maxlen=240)
        self.last_predict = float('-inf')
        self.last_accepted = None
        self.no_hand_since = None
        self.recent = deque(maxlen=2)
        self.result = self._state('collecting', 'Đưa tay vào khung và làm ký hiệu trong 3 giây')

    @staticmethod
    def _state(status, text, **extra):
        return {'status': status, 'label': None, 'text': text, 'confidence': None,
                'new_result': False, 'progress': 0.0, **extra}

    def close(self):
        self.hands.close()

    def process(self, image, now):
        import cv2
        # Recordings were mirrored BEFORE inference; preserve that convention.
        mirrored = cv2.flip(image, 1)
        feature = feature_from_result(self.hands.process(cv2.cvtColor(mirrored, cv2.COLOR_BGR2RGB)))
        return self.push(feature, now)

    def push(self, feature, now):
        if self.history and now - self.history[-1][0] > .5:
            self.history.clear()
            self.recent.clear()
        self.result = {**self.result, 'new_result': False}
        if not np.any(feature):
            self.recent.clear()
            if self.no_hand_since is None:
                self.no_hand_since = now
            if now - self.no_hand_since >= .5:
                self.history.clear()
                self.last_accepted = None
            elif self.history:
                self.history.append((now, np.array(feature, copy=True)))
            self.result = self._state('no_hands', 'Không thấy bàn tay')
            return dict(self.result)
        self.no_hand_since = None
        self.history.append((now, np.array(feature, copy=True)))
        while self.history and self.history[0][0] < now - 3.5:
            self.history.popleft()
        progress = min((now - self.history[0][0]) / 2.9, 1.0)
        if progress < 1:
            self.result = self._state('collecting', 'Đang quan sát cử chỉ…', progress=progress)
            return dict(self.result)
        if now - self.last_predict < .5:
            return dict(self.result)
        self.last_predict = now
        times = np.array([t for t, _ in self.history])
        grid = now - 2.9 + np.arange(30) * .1
        indices = np.abs(times[:, None] - grid).argmin(axis=0)
        if np.max(np.abs(times[indices] - grid)) > .15:
            self.recent.clear()
            self.result = self._state('uncertain', 'Camera quá chậm hoặc mất dấu tay; thử lại')
            return dict(self.result)
        prediction = self.model.predict(np.stack([self.history[i][1] for i in indices]))
        self.recent.append(prediction['label'] if prediction['accepted'] else None)
        stable = len(self.recent) == 2 and self.recent[0] == self.recent[1] and self.recent[0] is not None
        label = prediction['label']
        self.result = self._state(
            'recognized' if stable else 'stabilizing' if prediction['accepted'] else 'uncertain',
            LABEL_TEXT.get(label, label.replace('_', ' ')) if stable else 'Chưa rõ ký hiệu, giữ hoặc làm lại động tác',
            label=label.lower() if stable else None, confidence=prediction['confidence'],
            new_result=stable and label != self.last_accepted, progress=1.0)
        if stable:
            self.last_accepted = label
        return dict(self.result)
