"""Collect only confirmed GRU inputs for reviewed, offline training."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException


class GestureLearning:
    def __init__(self, store):
        self.store = store
        self.session = None
        self.recent = OrderedDict()
        self.live = None
        self.frozen = None
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS gesture_samples (
                id TEXT PRIMARY KEY, predicted TEXT NOT NULL, label TEXT NOT NULL,
                confidence REAL, session TEXT NOT NULL, model TEXT NOT NULL,
                captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'pending', digest TEXT NOT NULL UNIQUE,
                features BLOB NOT NULL)""")

    def toggle(self, enabled):
        if enabled and not self.session:
            self.session = uuid4().hex
        elif not enabled:
            self.session = None
            self.recent.clear()
            self.live = self.frozen = None

    def observe(self, result, model):
        features = result.get('learning_features')
        if not self.session or result.get('learning_session') != self.session or not features or not model:
            return
        self.recent[result['id']] = (monotonic(), result['label'], result.get('confidence'), model, features)
        self.live = result['id']
        if len(self.recent) > 6:
            oldest = next(key for key in self.recent if key != self.frozen)
            self.recent.pop(oldest)

    def candidate(self):
        if self.live not in self.recent:
            return None
        key = self.live
        captured, label, confidence, model, _ = self.recent[key]
        if monotonic() - captured <= 45:
            return {'id': key, 'label': label, 'confidence': confidence, 'labels': list(model['classes'])}
        return None

    def freeze(self, event):
        candidate = self.candidate()
        if not candidate or candidate['id'] != event:
            raise HTTPException(409, 'Ký hiệu đã thay đổi. Hãy làm lại ký hiệu.')
        self.frozen = event

    def confirm(self, event, label):

        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT label FROM gesture_samples WHERE id=?', (event,)).fetchone()
            if existing:
                if existing['label'].casefold() != label.casefold():
                    raise HTTPException(409, 'Mẫu này đã được xác nhận với nhãn khác.')
                return
            item = self.recent.get(event)
            if not self.session or event not in (self.live, self.frozen) or not item or monotonic() - item[0] > 45:
                raise HTTPException(409, 'Mẫu đã hết hạn. Hãy làm lại ký hiệu.')
            _, predicted, confidence, model, raw = item
            self._save(db, event, predicted, label, confidence, self.session, model, raw)
        self.recent.pop(event, None)
        if self.frozen == event:
            self.frozen = None
        if self.live == event:
            self.live = None

    def submit_mobile(self, event, predicted, label, confidence, session, model, raw, captured_at):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT label,predicted,session,model,digest FROM gesture_samples WHERE id=?', (event,)).fetchone()
            if existing:
                if (existing['label'].casefold() != label.casefold() or existing['predicted'].casefold() != predicted.casefold()
                        or existing['session'] != session or existing['model'] != model['sha256']
                        or existing['digest'] != hashlib.sha256(raw).hexdigest()):
                    raise HTTPException(409, 'Mã mẫu đã dùng cho dữ liệu khác.')
                return
            self._save(db, event, predicted, label, confidence, session, model, raw, captured_at)

    def _save(self, db, event, predicted, label, confidence, session, model, raw, captured_at=None):
        import numpy as np

        labels = {name.casefold(): name for name in model['classes']}
        if label.casefold() not in labels or predicted.casefold() not in labels:
            raise HTTPException(422, 'Nhãn nằm ngoài danh sách của model.')
        label = labels[label.casefold()]
        features = np.frombuffer(raw, dtype='<f4')
        if features.size != 30 * 126 or not np.isfinite(features).all() or not np.any(features.reshape(30, 126)[:, 63:], axis=1).all():
            raise HTTPException(422, 'Chuỗi keypoints thiếu hoặc không hợp lệ.')
        digest = hashlib.sha256(raw).hexdigest()
        if db.execute('SELECT 1 FROM gesture_samples WHERE digest=?', (digest,)).fetchone():
            raise HTTPException(409, 'Mẫu trùng đã có trong kho.')
        previous = db.execute('SELECT features FROM gesture_samples WHERE session=? AND label=?',
                              (session, label)).fetchall()
        if len(previous) >= 12:
            raise HTTPException(409, 'Phiên này đã đủ 12 mẫu cho nhãn. Hãy bắt đầu phiên mới.')
        # shortcut: fixed RMS threshold for exact model coordinates; calibrate from reviewed samples.
        if any(np.sqrt(np.mean((features - np.frombuffer(row['features'], dtype='<f4')) ** 2)) < .012
               for row in previous):
            raise HTTPException(409, 'Mẫu quá giống mẫu trong phiên. Hãy đổi góc hoặc vị trí tay.')
        if db.execute('SELECT COUNT(*) FROM gesture_samples').fetchone()[0] >= 2000:
            raise HTTPException(409, 'Kho mẫu đã đầy. Hãy xuất và quản lý mẫu trước khi thu thêm.')
        db.execute("""INSERT INTO gesture_samples(id,predicted,label,confidence,session,model,digest,features,captured_at)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                   (event, labels[predicted.casefold()], label, confidence, session, model['sha256'], digest, raw, captured_at or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))

    def review(self, event, action):
        with self.store.connect() as db:
            if action == 'delete':
                changed = db.execute("DELETE FROM gesture_samples WHERE id=? AND status!='trained'", (event,))
            else:
                allowed = ('approved',) if action == 'trained' else ('pending', 'approved', 'rejected')
                marks = ','.join('?' for _ in allowed)
                changed = db.execute(f'UPDATE gesture_samples SET status=? WHERE id=? AND status IN ({marks})',
                                     (action, event, *allowed))
            if not changed.rowcount:
                raise HTTPException(409, 'Không tìm thấy mẫu hoặc mẫu không còn ở trạng thái phù hợp.')

    def inventory(self, offset=0):
        with self.store.connect() as db:
            rows = db.execute("""SELECT id,predicted,label,confidence,session,model,captured_at,status
                                 FROM gesture_samples ORDER BY captured_at DESC,id LIMIT 50 OFFSET ?""", (offset,))
            counts = db.execute('SELECT label,status,COUNT(*) AS total FROM gesture_samples GROUP BY label,status')
            return {'items': [dict(row) for row in rows], 'counts': [dict(row) for row in counts]}

    def export(self, include_all=False):
        import base64

        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM gesture_samples' if include_all else
                              "SELECT * FROM gesture_samples WHERE status IN ('approved','trained')")
            return {'schema': 1, 'format': 'float32-le:30x126', 'samples': [
                {**dict(row), 'features': base64.b64encode(row['features']).decode('ascii')} for row in rows
            ]}
