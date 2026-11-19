"""Bridge the supplied Deafy checkpoint to the existing camera result contract."""
from pathlib import Path
import sys

import cv2
import mediapipe as mp
import torch

from landmark_recognition import LABEL_TEXT
from recognition_ranking import ranked_labels

# Reuse the exact training/inference helpers without changing the supplied package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Deafy_AI_share_ver0'))
from step2_collect_data import extract_features
from step5_train import load_checkpoint
from step6_inference_pipeline import DecisionGate, TimeWindow, predict, validate_preprocessing


class DeafyRecognizer:
    def __init__(self, path):
        torch.set_num_threads(1)
        self.model, self.checkpoint = load_checkpoint(path, device='cpu')
        prep = validate_preprocessing(self.checkpoint)
        self.labels = self.checkpoint['class_to_idx']
        # The supplied webcam demo defaults to 2s; this checkpoint was trained on 3s.
        self.window = TimeWindow(required='right', duration=prep['duration_seconds'],
                                 length=prep['sequence_length'])
        self.gate = DecisionGate(threshold=.7, stable_count=3, cooldown=2.0)
        self.last_predict = float('-inf')
        self.last_candidate = float('-inf')
        self.candidate_label, self.candidate_count = None, 0
        self.overlay_hands = []
        self.feedback_sequence = None
        self.result = self._state('collecting', 'Đưa tay vào khung và làm ký hiệu trong 3 giây')
        predict(self.model, torch.zeros(1, 30, 126).numpy(), self.labels)
        self.hands = mp.solutions.hands.Hands(
            max_num_hands=2, model_complexity=1,
            min_detection_confidence=.5, min_tracking_confidence=.5)

    @staticmethod
    def _state(status, text, **extra):
        return {'status': status, 'text': text, 'label': None, 'confidence': None,
                'new_result': False, 'progress': 0.0, **extra}

    def close(self):
        self.hands.close()

    def process(self, image, now):
        mirrored = cv2.flip(image, 1)
        features, mask = extract_features(self.hands.process(cv2.cvtColor(mirrored, cv2.COLOR_BGR2RGB)))
        # JPEG uses the original camera orientation; the UI mirrors it for display.
        self.overlay_hands = [[[1 - p[0], p[1]] for p in hand]
                              for hand, visible in zip(features.reshape(2, 21, 3), mask) if visible]
        return self.push(features, mask, now)

    def push(self, features, mask, now):
        self.feedback_sequence = None
        reason = self.window.add(now, features, mask)
        self.result = {**self.result, 'new_result': False, 'new_candidate': False}
        if reason:
            self.gate.reset()
            self.candidate_label, self.candidate_count = None, 0
            self.result = self._state('no_hands' if not mask.any() else 'collecting',
                                      'Không thấy bàn tay' if not mask.any() else 'Camera bị ngắt nhịp; làm lại ký hiệu')
        elif self.window.coverage < self.window.duration:
            self.result = self._state('collecting', 'Đang quan sát cử chỉ…',
                                      progress=self.window.coverage / self.window.duration)
        elif now - self.last_predict >= .2:
            sequence = self.window.sample()
            if sequence is not None:
                import numpy as np
                with torch.inference_mode():
                    logits = self.model(torch.from_numpy(np.asarray(sequence, dtype=np.float32)))
                    if logits.shape != (1, len(self.labels)) or not torch.isfinite(logits).all():
                        raise ValueError('Invalid model logits')
                    ranked = ranked_labels(logits.softmax(dim=1)[0].tolist(), self.labels)
                inverse = {label.lower(): label for label in self.labels}
                label, score = inverse[ranked[0]['label']], ranked[0]['confidence']
                accepted, emitted = self.gate.update(label, score, now)
                self.candidate_count = self.candidate_count + 1 if label == self.candidate_label else 1
                self.candidate_label = label
                candidate = not accepted and self.candidate_count >= 3 and now - self.last_candidate >= 2
                if candidate:
                    self.last_candidate = now
                if emitted or candidate:
                    self.feedback_sequence = sequence
                self.result = dict(status='recognized' if accepted else 'stabilizing' if score >= .7 else 'uncertain',
                                   text=LABEL_TEXT.get(label, label.replace('_', ' ')) if accepted else 'Chưa rõ ký hiệu, giữ hoặc làm lại động tác',
                                   label=label.lower() if accepted else None,
                                   confidence=score, new_result=emitted, new_candidate=candidate,
                                   top_candidates=ranked, progress=1.0)
                self.last_predict = now
        return {**self.result, 'elapsed_seconds': min(self.window.coverage, self.window.duration),
                'window_seconds': self.window.duration}
