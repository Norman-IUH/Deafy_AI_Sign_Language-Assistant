"""GRU with the supplied training tracker's slot and interpolation rules."""
from collections import deque
import itertools
import math

import numpy as np
import torch
from torch import nn

MAX_MISSING = 15
WINDOW_SEC = 3.0
PREDICT_INTERVAL = 0.5
# Chosen on Deafy_ver3 validation clips; reduces false accepts at lower coverage.
MIN_SCORE = 0.85
MIN_WINDOW_FRAMES = 15
PRE_ROLL_SEC = 0.4
POST_ROLL_SEC = 0.4
MIN_SEGMENT_FRAMES = 8
MIN_HAND_FRAMES = 4
MIN_SHORT_FPS = 10.0
LABEL_TEXT = {
    "bat_den": "Bật đèn", "dong_y": "Đồng ý", "khong_dong_y": "Không đồng ý",
    "tam_biet": "Tạm biệt", "xin_chao": "Xin chào", "dau_hoi": "Dấu hỏi",
    "dau_huyen": "Dấu huyền", "dau_nang": "Dấu nặng", "dau_nga": "Dấu ngã",
    "dau_sac": "Dấu sắc", "blank": "",
}

class SignGRU(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, num_classes):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, num_layers=num_layers,
                          batch_first=True, dropout=0.3 if num_layers > 1 else 0)
        self.classifier = nn.Sequential(
            nn.LayerNorm(hidden_size), nn.Linear(hidden_size, 32),
            nn.ReLU(), nn.Dropout(0.3), nn.Linear(32, num_classes)
        )

    def forward(self, x):
        _, h = self.gru(x)
        return self.classifier(h[-1])


def make_feature(det, status='observed'):
    vec = np.zeros(48, np.float32)
    if det is None:
        return vec
    x1, y1, x2, y2 = det['box']
    bw, bh = x2 - x1, y2 - y1
    if bw <= 1e-6 or bh <= 1e-6:
        return vec
    kp = det['kp']
    wx, wy = kp[0, :2]
    for k in range(21):
        vec[2*k] = np.clip((kp[k, 0] - wx) / bw, -3, 3)
        vec[2*k+1] = np.clip((kp[k, 1] - wy) / bh, -3, 3)
    vec[42:46] = [(x1+x2)/2, (y1+y2)/2, bw, bh]
    vec[46] = float(status == 'observed')
    vec[47] = float(status == 'interpolated')
    return vec


class Slot:
    def __init__(self, number):
        self.number = number
        self.center = None
        self.velocity = np.zeros(2, dtype=float)
        self.scale = None
        self.pose = None
        self.missing = 10000

    def predicted(self):
        return self.center + self.velocity * min(self.missing + 1, 4)

    def cost(self, det):
        if self.center is None or self.missing > 15:
            return None
        dc = np.linalg.norm(self.predicted() - det['center'])
        # Relative movement gate; larger box allows modestly larger displacement.
        gate = min(.35, max(.12, 2.2 * max(self.scale or .05, det['scale'])))
        if dc > gate:
            return None
        size_penalty = abs(math.log((det['scale'] + 1e-6) / (self.scale + 1e-6)))
        pose_penalty = 0.0
        if self.pose is not None and det['pose'] is not None:
            # Pose is wrist-relative and box-scale normalized.
            pose_penalty = min(float(np.mean(np.linalg.norm(self.pose - det['pose'], axis=1))), 2.0)
        return dc + 0.04 * size_penalty + 0.025 * pose_penalty

    def update(self, det):
        if self.center is not None and self.missing <= 15:
            dt = self.missing + 1
            measured_velocity = (det['center'] - self.center) / dt
            self.velocity = .5 * self.velocity + .5 * measured_velocity
        else:
            self.velocity[:] = 0
        self.center = det['center']
        self.scale = det['scale']
        self.pose = det['pose']
        self.missing = 0

    def miss(self):
        self.missing += 1
        self.velocity *= .85


def match(slots, detections, max_missing):
    # Exhaustive global assignment: at most two slots, up to six detections.
    # Each slot can independently remain unmatched; avoid greedy conflicting assignments.
    best_assign, best_cost = {}, float('inf')
    choices = [None] + list(range(len(detections)))
    for a, b in itertools.product(choices, repeat=2):
        if a is not None and a == b:
            continue
        proposal = [a,b]
        score = 0.0
        valid = True
        for slot, idx in zip(slots, proposal):
            if idx is None:
                score += .28 if slot.center is not None else .45
                continue
            c = slot.cost(detections[idx])
            if c is None:
                if slot.center is None or slot.missing > max_missing:
                    c = .23 - .05 * detections[idx]['conf']
                else:
                    valid = False
                    break
            score += c
        if valid and score < best_cost:
            best_cost, best_assign = score, {i+1:idx for i,idx in enumerate(proposal) if idx is not None}

    if not best_assign and all(s.center is None or s.missing > max_missing for s in slots):
        # First appearance: initialize by image x position.
        candidate = sorted(range(min(2,len(detections))), key=lambda i:detections[i]['center'][0])
        best_assign = {i+1:idx for i,idx in enumerate(candidate)}
    # If both slots are expired, new initialization from L/R image (not anatomical labels).
    if all(s.missing > max_missing for s in slots) and len(detections)>=2:
        idxs = sorted(range(min(2,len(detections))), key=lambda i:detections[i]['center'][0])
        best_assign = {1:idxs[0],2:idxs[1]}
    return best_assign


class TwoHandTracker:
    def __init__(self):
        self.slots = [Slot(1), Slot(2)]

    def update(self, detections):
        detections = sorted(detections, key=lambda d: -d['conf'])[:6]
        for det in detections:
            x1, y1, x2, y2 = det['box']
            det['center'] = np.array([(x1+x2)/2, (y1+y2)/2])
            det['scale'] = max(x2-x1, y2-y1, .005)
            pose = (det['kp'][:, :2] - det['kp'][0, :2]) / det['scale']
            det['pose'] = pose if det['kp'][0, 2] >= .25 else None
        assigned = {slot-1: index for slot, index in match(self.slots, detections, MAX_MISSING).items()}
        features = []
        for si, slot in enumerate(self.slots):
            det = detections[assigned[si]] if si in assigned else None
            if det is None:
                slot.miss()
            else:
                slot.update(det)
            features.append(make_feature(det))
        return np.concatenate(features), assigned, detections


def sequence_from_hands(frames):
    """Match training: interpolate only bounded gaps, then sample 30 frames."""
    features = np.zeros((len(frames), 96), np.float32)
    for slot in range(2):
        observed = [i for i, pair in enumerate(frames) if pair[slot] is not None]
        for i in observed:
            features[i, slot*48:(slot+1)*48] = make_feature(frames[i][slot])
        for left, right in zip(observed, observed[1:]):
            if right-left-1 > 5:
                continue
            a, b = frames[left][slot], frames[right][slot]
            for i in range(left+1, right):
                ratio = (i-left)/(right-left)
                det = {key: (1-ratio)*a[key]+ratio*b[key] for key in ('box', 'kp')}
                features[i, slot*48:(slot+1)*48] = make_feature(det, 'interpolated')
    chosen = np.rint(np.linspace(0, len(frames)-1, 30)).astype(int)
    return features[chosen]



def load_gru(path, device):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint["input_size"] != 96 or checkpoint["sequence_length"] != 30:
        raise ValueError("Checkpoint cần đầu vào (30, 96) như code train được cung cấp.")
    labels = list(checkpoint["labels"])
    if not labels or len(set(labels)) != len(labels) or not all(isinstance(x, str) for x in labels):
        raise ValueError("Danh sách nhãn checkpoint không hợp lệ.")
    model = SignGRU(checkpoint["input_size"], checkpoint["hidden_size"],
                    checkpoint["num_layers"], len(labels)).to(device)
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.checkpoint_epoch = checkpoint.get("best_epoch")
    model.sequence_length = checkpoint["sequence_length"]
    model.input_size = checkpoint["input_size"]
    model.eval()
    return model, labels


class RollingRecognizer:
    def __init__(self, model, labels, device):
        self.model, self.labels, self.device = model, labels, device
        self.inference_count = 0
        self.reset()

    def reset(self):
        self.tracker = TwoHandTracker()
        self.history = deque(maxlen=180)
        self.recent = deque(maxlen=3)
        self.no_hand_since = None
        self.blank_active = False
        self.last_predict = 0.0
        self.last_seen = None
        self.last_accepted = None
        self.pre_roll = deque(maxlen=60)
        self.short_frames = None
        self.short_first = self.short_last = None
        self.short_handled = False
        self.short_result = None
        self.short_result_until = 0
        self.result = {"status": "collecting", "label": None, "text": "Đang quan sát cử chỉ…",
                       "confidence": None, "progress": 0.0, "new_result": False}

    def _probabilities(self, sequences):
        with torch.inference_mode():
            probabilities = torch.softmax(
                self.model(torch.from_numpy(sequences).to(self.device)), dim=1).cpu().numpy()
        self.inference_count += 1
        return probabilities

    def _prediction(self, probabilities, stable):
        predicted = int(np.argmax(probabilities))
        confidence = float(probabilities[predicted])
        label = self.labels[predicted]
        status = "recognized" if stable and label != "blank" else ("uncertain" if confidence < MIN_SCORE else "stabilizing")
        text = LABEL_TEXT.get(label, label.replace("_", " ")) if status == "recognized" else "Chưa rõ ký hiệu"
        if label == "blank" and stable:
            status, text = "blank", "Chưa có ký hiệu"
        is_new = status == "recognized" and label != self.last_accepted
        if status == "recognized":
            self.last_accepted = label
        elif status == "blank":
            self.last_accepted = None
        return {"status": status, "label": label if status == "recognized" else None,
                "text": text, "confidence": confidence, "progress": 1.0, "new_result": is_new,
                "candidates": [{"label": self.labels[int(i)], "confidence": float(probabilities[i])}
                               for i in np.argsort(probabilities)[::-1][:3]]}

    def _collect_short(self, hands, now):
        # A completed isolated gesture has a different boundary from a held 3-second window.
        present = any(hand is not None for hand in hands)
        if self.short_result is not None:
            self.short_result['new_result'] = False
        if present:
            self.short_result = None
            if self.short_frames is None:
                self.short_frames = deque((entry for entry in self.pre_roll if entry[0] >= now-PRE_ROLL_SEC-1e-6), maxlen=180)
                self.short_first = now
                self.short_handled = False
            self.short_last = now
        if self.short_frames is not None:
            self.short_frames.append((now, hands))
            if self.result['status'] == 'recognized' or self.short_last-self.short_first > WINDOW_SEC:
                self.short_handled = True
            if not present and now-self.short_last >= POST_ROLL_SEC-1e-6:
                frames = [pair for _, pair in self.short_frames]
                observed = sum(any(h is not None for h in pair) for pair in frames)
                if (not self.short_handled and len(frames) >= MIN_SEGMENT_FRAMES
                        and observed >= MIN_HAND_FRAMES and observed/len(frames) >= .25
                        and self.short_last-self.short_first >= .25):
                    span = self.short_frames[-1][0]-self.short_frames[0][0]
                    fps = (len(frames)-1)/span
                    evidence = {'mode':'completed_segment', 'frames':len(frames),
                                'hand_frames':observed, 'seconds':span, 'effective_fps':fps}
                    if fps+1e-6 < MIN_SHORT_FPS:
                        evidence['rejection'] = 'insufficient_short_fps'
                        self.short_result = {'status':'uncertain', 'label':None, 'confidence':None,
                                             'text':'Ảnh gửi quá chậm cho ký hiệu ngắn. Tắt bớt camera hoặc thử lại.',
                                             'progress':1.0, 'new_result':False}
                    else:
                        # Check boundary sensitivity with existing frames; never invent hand observations.
                        views = [frames, frames[1:] if all(h is None for h in frames[0]) else frames[:-2], frames[:-1]]
                        probabilities = self._probabilities(np.stack([sequence_from_hands(view) for view in views]))
                        mean = probabilities.mean(axis=0)
                        consistent = (len(set(probabilities.argmax(axis=1).tolist())) == 1
                                      and bool(np.all(probabilities.max(axis=1) >= MIN_SCORE)))
                        self.last_accepted = None
                        self.short_result = self._prediction(mean, consistent)
                        if not consistent:
                            self.short_result.update(status='uncertain', label=None, new_result=False)
                            if float(mean.max()) >= MIN_SCORE:
                                self.short_result['text'] = 'Ranh giới ký hiệu chưa ổn định. Hãy thực hiện lại.'
                        evidence['boundary_views'] = len(views)
                    self.short_result['evidence'] = evidence
                    self.short_result_until = now + 1.2
                self.short_frames = None
                self.history.clear()
                self.recent.clear()
                self.tracker = TwoHandTracker()
                self.blank_active = True
                self.last_accepted = None
        self.pre_roll.append((now, hands))
        while self.pre_roll and self.pre_roll[0][0] < now-PRE_ROLL_SEC-1e-6:
            self.pre_roll.popleft()
        return dict(self.short_result) if self.short_result is not None and now < self.short_result_until else None

    def push(self, detections, now):
        if self.last_seen is not None and now - self.last_seen > WINDOW_SEC:
            self.reset()
        self.last_seen = now
        self.result["new_result"] = False
        _, assigned, tracked = self.tracker.update(detections)
        hands = [tracked[assigned[i]] if i in assigned else None for i in range(2)]
        completed = self._collect_short(hands, now)
        if assigned:
            self.no_hand_since = None
            if self.blank_active:
                self.blank_active = False
                self.history.clear()
                self.recent.clear()
                self.tracker = TwoHandTracker()
                _, assigned, tracked = self.tracker.update(detections)
                self.result = {"status": "collecting", "label": None, "text": "Đang quan sát cử chỉ…",
                               "confidence": None, "progress": 0.0, "new_result": False}
        elif self.no_hand_since is None:
            self.no_hand_since = now
        if self.no_hand_since is not None and now - self.no_hand_since >= 0.5:
            self.blank_active = True
            self.history.clear()
            self.recent.clear()
            self.tracker = TwoHandTracker()
            self.last_accepted = None
            self.last_predict = now
            self.result = {"status": "no_hands", "label": None, "text": "Không thấy bàn tay",
                           "confidence": None, "progress": 0.0, "new_result": False}
        if not self.blank_active:
            hands = [tracked[assigned[i]] if i in assigned else None for i in range(2)]
            self.history.append((now, hands))
        while self.history and self.history[0][0] < now - WINDOW_SEC - 0.5:
            self.history.popleft()
        if not assigned:
            # Even a short gap breaks consecutive evidence; never revive an old confirmation.
            self.recent.clear()
            self.result = {"status": "collecting", "label": None, "text": "Đang quan sát lại cử chỉ…",
                           "confidence": None, "progress": 0.0, "new_result": False}
            return completed or {**self.result, "status": "no_hands", "text": "Không thấy bàn tay"}, assigned, tracked
        if not self.history:
            return dict(self.result), assigned, tracked
        duration = now - self.history[0][0]
        self.result["progress"] = min(duration / WINDOW_SEC, 1.0)
        if duration < WINDOW_SEC - 0.05 or now - self.last_predict < PREDICT_INTERVAL:
            return dict(self.result), assigned, tracked

        times = np.array([t for t, _ in self.history])
        start = int(np.argmin(abs(times - (now - WINDOW_SEC))))
        frames = [hands for _, hands in list(self.history)[start:]]
        if len(frames) < MIN_WINDOW_FRAMES:
            self.recent.clear()
            self.result = {"status": "uncertain", "label": None,
                           "text": "Camera gửi ảnh quá chậm. Đóng bớt app camera và thử lại.",
                           "confidence": None, "progress": 1.0, "new_result": False}
            return dict(self.result), assigned, tracked
        sequence = sequence_from_hands(frames)
        observed_fraction = float(np.mean(np.maximum(sequence[:, 46], sequence[:, 94])))
        self.last_predict = now
        if observed_fraction < 0.25:
            self.recent.clear()
            self.result = {"status": "uncertain", "label": None, "text": "Chưa thấy rõ cử chỉ",
                           "confidence": None, "progress": 1.0, "new_result": False}
            return dict(self.result), assigned, tracked
        probabilities = self._probabilities(sequence[None])[0]
        predicted = int(np.argmax(probabilities))
        confidence = float(probabilities[predicted])
        self.recent.append(predicted if confidence >= MIN_SCORE else -1)
        stable = len(self.recent) == 3 and len(set(self.recent)) == 1 and self.recent[0] >= 0
        self.result = self._prediction(probabilities, stable)
        return dict(self.result), assigned, tracked
