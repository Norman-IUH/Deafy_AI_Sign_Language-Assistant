"""One optional camera/inference worker; no AI imports at application startup."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4


def draw_hand_overlay(image, hands):
    import cv2
    from math import isfinite
    height, width = image.shape[:2]
    for hand in hands:
        if len(hand) != 21 or not all(isfinite(x) and isfinite(y) for x, y in hand):
            continue
        points = [(round(max(0, min(1, x)) * (width - 1)),
                   round(max(0, min(1, y)) * (height - 1))) for x, y in hand]
        for path in ((0, 1, 2, 3, 4), (0, 5, 6, 7, 8), (5, 9, 10, 11, 12),
                     (9, 13, 14, 15, 16), (13, 17, 18, 19, 20), (0, 17)):
            for a, b in zip(path, path[1:]):
                cv2.line(image, points[a], points[b], (170, 245, 90), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(image, point, 4, (20, 30, 20), -1, cv2.LINE_AA)
            cv2.circle(image, point, 2, (255, 255, 255), -1, cv2.LINE_AA)
    return image


class CameraService:
    def __init__(self, root):
        self.root = Path(root)
        self.deafy_checkpoint = self.root.parent / 'Deafy_AI_share_ver0/artifacts/step5/run_20261026T045637Z_ebe324f6/best_model.pth'
        self.checkpoint_configured = bool(os.getenv('DAKT_GRU_CHECKPOINT'))
        if self.checkpoint_configured:
            self.deafy_checkpoint = self.root.parent / os.environ['DAKT_GRU_CHECKPOINT']
        self.model_info = None
        self.lock = Lock()
        self.lifecycle_lock = Lock()
        self.stop_event = Event()
        self.thread = None
        self.jpeg = None
        self.frame_image = None
        self.frame_hands = []
        self.running = False
        self.error = None
        self.model_error = None
        self.model_ready = False
        self.serial = 0
        self.pending = deque(maxlen=20)
        self.learning_session = None
        self.recognition = {'status': 'unavailable', 'text': '', 'confidence': None}

    def ai_status(self):
        landmarks = (self.root / 'data/landmark_templates.npz').is_file()
        deafy = self.deafy_checkpoint.is_file()
        present = deafy or landmarks or all((self.root / 'data' / name).is_file() for name in ('hand_pose.pt', 'gru_best.pt'))
        return {'ready': self.model_ready, 'model_present': present,
                'status': 'ready' if self.model_ready else ('error' if self.model_error else 'not_loaded' if present else 'missing'),
                'message': self.model_error or ('Mô hình đã sẵn sàng.' if self.model_ready else 'Bật camera để nạp mô hình.' if present else 'Chưa có mô hình'),
                'model': self.model_info if self.model_ready else None,
                'pipeline': f'{self.model_info["name"]} · MediaPipe + GRU ({self.model_info["num_classes"]} ký hiệu)' if self.model_ready and self.model_info else 'Deafy · MediaPipe + GRU' if deafy or self.checkpoint_configured else 'MediaPipe + mẫu cử chỉ (thử nghiệm)' if landmarks else 'YOLO pose + GRU'}

    def status(self):
        return {'running': self.running, 'error': self.error, 'source': 'server', 'has_frame': self.jpeg is not None}

    def frame(self, landmarks=False):
        with self.lock:
            if not landmarks or self.frame_image is None or not self.frame_hands:
                return self.jpeg
            image, hands = self.frame_image.copy(), self.frame_hands
        import cv2
        ok, encoded = cv2.imencode('.jpg', draw_hand_overlay(image, hands), [cv2.IMWRITE_JPEG_QUALITY, 75])
        return encoded.tobytes() if ok else None

    def take_result(self):
        with self.lock:
            return self.pending.popleft() if self.pending else None

    def start(self):
        with self.lifecycle_lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.error = None
            self.thread = Thread(target=self._run, daemon=True, name='camera-inference')
            self.thread.start()

    def stop(self):
        with self.lifecycle_lock:
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=5)
            with self.lock:
                self.jpeg = None
                self.frame_image = None
                self.frame_hands = []
                self.running = False
                self.model_ready = False
                self.recognition = {'status': 'unavailable', 'text': '', 'confidence': None}
                self.pending.clear()
                self.serial += 1

    def _load_recognizer(self):
        if self.deafy_checkpoint.is_file() or self.checkpoint_configured:
            if not self.deafy_checkpoint.is_file():
                raise ValueError('Không tìm thấy checkpoint GRU đã cấu hình; không tự dùng model khác.')
            digest = hashlib.sha256(self.deafy_checkpoint.read_bytes()).hexdigest()
            expected = os.getenv('DAKT_GRU_SHA256', '').lower()
            if expected and digest != expected:
                raise ValueError('Checksum checkpoint GRU không khớp; không nạp model.')
            from deafy_recognition import DeafyRecognizer
            recognizer = DeafyRecognizer(self.deafy_checkpoint)
            self.model_info = {'name': os.getenv('DAKT_GRU_NAME', 'Deafy'), 'version': self.deafy_checkpoint.parent.name,
                               'sha256': digest, 'num_classes': len(recognizer.labels), 'classes': recognizer.labels}
            report_path = self.deafy_checkpoint.with_name('evaluation.json')
            if report_path.is_file() and report_path.stat().st_size < 200_000:
                try:
                    report = json.loads(report_path.read_text(encoding='utf-8'))
                    if report.get('candidate_sha256') == digest and report.get('passes_quality_gate') is True:
                        self.model_info['evaluation'] = {name: report[name]['macro_f1'] for name in ('baseline', 'candidate')}
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    pass
            self.model_ready = True
            return None, recognizer
        if (self.root / 'data/landmark_templates.npz').is_file():
            from landmark_recognition import LandmarkRecognizer
            recognizer = LandmarkRecognizer(self.root / 'data/landmark_templates.npz')
            self.model_ready = True
            return None, recognizer
        if not self.ai_status()['model_present']:
            return None, None
        from ultralytics import YOLO
        from sign_recognition import load_gru, RollingRecognizer
        detector = YOLO(str(self.root / 'data/hand_pose.pt'))
        if detector.task != 'pose' or list(getattr(detector.model, 'kpt_shape', [])) != [21, 3]:
            raise ValueError('Mô hình điểm tay cần 21 điểm (YOLO pose).')
        model, labels = load_gru(self.root / 'data/gru_best.pt', 'cpu')
        self.model_ready = True
        return detector, RollingRecognizer(model, labels, 'cpu')

    def _run(self):
        capture = None
        recognizer = None
        try:
            import cv2
            capture = cv2.VideoCapture(int(os.getenv('DAKT_CAMERA_INDEX', '0')))
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                raise RuntimeError('Không mở được camera máy chủ. Kiểm tra camera hoặc DAKT_CAMERA_INDEX.')
            self.running = True
            self.model_error = None
            try:
                detector, recognizer = self._load_recognizer()
            except Exception as exc:
                self.model_error = str(exc)
                detector, recognizer = None, None
            self.serial += 1
            while not self.stop_event.is_set():
                began = monotonic()
                ok, image = capture.read()
                if not ok:
                    raise RuntimeError('Camera không trả hình. Tắt và bật lại camera để thử lại.')
                result = None
                if recognizer is not None and detector is None:
                    result = recognizer.process(image, monotonic())
                elif detector is not None:
                    import numpy as np
                    height, width = image.shape[:2]
                    pose = detector.predict(image, imgsz=640, conf=.2, device='cpu', verbose=False)[0]
                    candidates = []
                    if pose.boxes is not None and pose.keypoints is not None:
                        for box, score, points in zip(pose.boxes.xyxy.cpu().numpy(), pose.boxes.conf.cpu().numpy(), pose.keypoints.data.cpu().numpy()):
                            if len(points) >= 21:
                                candidates.append({'box': box / [width,height,width,height],
                                    'kp': points[:21] / np.array([width,height,1]), 'conf': float(score)})
                    result, _, _ = recognizer.push(candidates, monotonic())
                ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self.lock:
                    if ok:
                        if self.jpeg is None:
                            self.serial += 1
                        self.jpeg = encoded.tobytes()
                        self.frame_image = image
                        self.frame_hands = getattr(recognizer, 'overlay_hands', [])
                    if result:
                        self.recognition = result
                        if (result.get('new_result') and result.get('label')) or result.get('new_candidate'):
                            ranked = result.get('top_candidates', [])
                            event = {'id': uuid4().hex, 'label': result.get('label') or ranked[0]['label'],
                                'text': result.get('text', ''), 'captured_at': began, 'confirmed': bool(result.get('new_result')),
                                'confidence': result.get('confidence'), 'candidates': ranked}
                            session = self.learning_session
                            sequence = getattr(recognizer, 'feedback_sequence', None)
                            if session and sequence is not None:
                                event.update(learning_session=session, learning_features=sequence.astype('<f4', copy=False).tobytes())
                            self.pending.append(event)
                        self.serial += 1
                self.stop_event.wait(max(0, 1/30 - (monotonic() - began)))
        except ImportError:
            self.error = 'Chưa cài thư viện camera. Cài requirements-camera.txt rồi bật lại camera.'
        except Exception as exc:
            self.error = str(exc)
        finally:
            if recognizer is not None and hasattr(recognizer, 'close'):
                recognizer.close()
            if capture is not None:
                capture.release()
            with self.lock:
                self.running = False
                self.jpeg = None
                self.frame_image = None
                self.frame_hands = []
                self.model_ready = False
                self.serial += 1
