"""Loopback-only webcam experiment. No production DB, cloud, MQTT or Pi imports."""
import argparse
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from threading import Lock
from pathlib import Path
from statistics import median
from time import monotonic, perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from starlette.middleware.trustedhost import TrustedHostMiddleware

from model_test_profiles import ROOT, PROFILES, checkpoint_path, model_schemas
from model_benchmark_data import save_capture, dataset_counts
from recognition_service import CameraService


class TestCamera(CameraService):
    def __init__(self, profile):
        super().__init__(ROOT / 'backend')
        self.deafy_checkpoint = checkpoint_path(profile)
        self.info = None
        self.times = deque(maxlen=240)
        self.pipeline_ms = deque(maxlen=240)
        self.gru_ms = deque(maxlen=240)
        self.frame_count = 0
        self.capture_lock, self.capture_buffer = Lock(), None

    def begin_capture(self, start, end):
        with self.capture_lock:
            self.capture_buffer = {'start': start, 'end': end, 'frames': [], 'masks': [], 'times': []}

    def end_capture(self):
        with self.capture_lock:
            data, self.capture_buffer = self.capture_buffer, None
        return data

    def _load_recognizer(self):
        detector, recognizer = super()._load_recognizer()
        c = recognizer.checkpoint
        self.info = {'version': self.deafy_checkpoint.parent.name, 'classes': recognizer.labels,
                     'config': c['model_config'], 'preprocessing': c['preprocessing'],
                     'threshold': .7, 'stable_count': 3, 'cooldown_seconds': 2, 'required_hands': 'right'}
        original = recognizer.process
        original_push = recognizer.push

        def record_push(features, mask, now):
            with self.capture_lock:
                data = self.capture_buffer
                if data and data['start'] <= now <= data['end'] and len(data['times']) < 1200:
                    data['frames'].append(features.copy())
                    data['masks'].append(mask.copy())
                    data['times'].append(now - data['start'])
            return original_push(features, mask, now)
        recognizer.push = record_push
        started = [0.0]
        recognizer.model.register_forward_pre_hook(lambda *args: started.__setitem__(0, perf_counter()))
        recognizer.model.register_forward_hook(lambda *args: self.gru_ms.append((perf_counter() - started[0]) * 1000))

        def measured(image, now):
            began = perf_counter()
            result = original(image, now)
            self.times.append(now)
            self.frame_count += 1
            self.pipeline_ms.append((perf_counter() - began) * 1000)
            return result
        recognizer.process = measured
        return detector, recognizer

    def metrics(self):
        times, pipeline, gru = list(self.times), list(self.pipeline_ms), list(self.gru_ms)
        return {'fps': round((len(times)-1)/(times[-1]-times[0]), 1) if len(times) > 1 and times[-1] > times[0] else None,
                'pipeline_ms_median': round(median(pipeline), 2) if pipeline else None,
                'gru_ms_median': round(median(gru), 2) if gru else None}


class Selection(BaseModel):
    profile: str


class Trial(BaseModel):
    label: str | None = None


class Capture(BaseModel):
    subject: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    session: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    split: Literal['validation', 'test']
    condition: Literal['normal', 'low_light', 'busy_background']
    kind: Literal['gesture', 'no_gesture', 'random_motion', 'unknown_sign']
    label: str | None = None


def create_test_app(profile='new', output=None, session=None, camera_factory=TestCamera):
    output = Path(output) if output else ROOT / '.tools/model-test'
    output.mkdir(parents=True, exist_ok=True)
    session = session or uuid4().hex
    camera = camera_factory(profile)
    events, trials = deque(maxlen=100), deque(maxlen=100)
    trial = None
    capture, last_capture = None, None
    captures_root = output / 'benchmark-data'
    counts = dataset_counts(captures_root)
    lifecycle = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(camera.stop)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    app.state.camera = camera
    app.state.shutdown = None

    @app.middleware('http')
    async def isolate(request: Request, call_next):
        if request.method not in ('GET', 'HEAD') and request.headers.get('x-model-test-session') != session:
            return Response('Mở trang thử trước khi thao tác.', status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    def snapshot():
        nonlocal trial, capture, last_capture, counts
        if capture and monotonic() >= capture['ends']:
            data = camera.end_capture()
            try:
                row, path = save_capture(captures_root, capture['metadata'], data['frames'], data['masks'], data['times'])
                counts = dataset_counts(captures_root)
                last_capture = {'status': 'saved', 'path': path, 'frames': row['frames'], 'capture_fps': round(row['capture_fps'], 1)}
            except (ValueError, OSError) as exc:
                last_capture = {'status': 'error', 'message': str(exc)}
            capture = None
        while event := camera.take_result():
            if event.get('confirmed', True):
                events.append(event)
                if trial and trial['started'] <= event['captured_at'] <= trial['ends']:
                    trial['events'].append(event)
        if trial and monotonic() >= trial['ends']:
            labels = [e['label'] for e in trial['events']]
            row = {'id': trial['id'], 'created_at': datetime.now(timezone.utc).isoformat(),
                   'profile': profile, 'sha256': PROFILES[profile]['sha256'], 'user_expected_label': trial['label'],
                   'seconds': 10, 'confirmed_labels': labels, 'metrics': camera.metrics(),
                   'false_positive_events': len(labels) if trial['label'] is None else None,
                   'matched': trial['label'].lower() in labels if trial['label'] else None,
                   'unexpected_events': sum(label != (trial['label'] or '').lower() for label in labels),
                   'frames_processed': camera.frame_count - trial['frames'],
                   'valid_capture': camera.running and camera.model_ready and camera.frame_count > trial['frames'],
                   'ground_truth': 'user_selected_not_independently_verified'}
            with (output / 'trials.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            trials.append(row)
            trial = None
        with camera.lock:
            recognition = dict(camera.recognition)
        return {'service': 'DAKT-Nc-model-test', 'session': session, 'profile': profile,
                'profiles': {key: {'name': value['name'], 'sha256': value['sha256']} for key, value in PROFILES.items()},
                'model': camera.info, 'camera': camera.status(), 'model_error': camera.model_error,
                'recognition': recognition, 'metrics': camera.metrics(), 'events': list(events), 'trials': list(trials),
                'trial': {'label': trial['label'], 'remaining': max(0, round(trial['ends'] - monotonic(), 1))} if trial else None,
                'benchmark': {'vocabulary': sorted(set().union(*(set(s['classes']) for s in model_schemas().values()))),
                              'capture': {'phase': 'preparing' if monotonic() < capture['started'] else 'recording',
                                          'remaining': max(0, round((capture['started'] if monotonic() < capture['started'] else capture['ends']) - monotonic(), 1))} if capture else None,
                              'last_capture': last_capture, 'counts': counts, 'report_ready': (ROOT/'.tools/model-benchmark/latest/report.md').is_file(),
                              'hybrid': 'NOT_ELIGIBLE: cần validation/test độc lập đủ mẫu'},
                'isolation': 'Windows only; no Pi, cloud, MQTT or production database'}

    @app.get('/api/state')
    async def state():
        return snapshot()

    @app.post('/api/camera/start')
    async def start():
        async with lifecycle:
            checkpoint_path(profile)
            await asyncio.to_thread(camera.start)
        return snapshot()

    @app.post('/api/camera/stop')
    async def stop():
        nonlocal trial, capture, last_capture
        async with lifecycle:
            trial = None
            if capture:
                camera.end_capture()
                capture = None
                last_capture = {'status': 'cancelled', 'message': 'Đã hủy thu mẫu do tắt camera.'}
            await asyncio.to_thread(camera.stop)
        return snapshot()

    @app.post('/api/model')
    async def select(body: Selection):
        nonlocal camera, profile
        try:
            checkpoint_path(body.profile)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from None
        async with lifecycle:
            snapshot()
            if trial or capture:
                raise HTTPException(409, 'Chờ lượt đánh giá xong trước khi đổi model.')
            if body.profile != profile:
                running = camera.running
                await asyncio.to_thread(camera.stop)
                if camera.thread and camera.thread.is_alive():
                    raise HTTPException(409, 'Camera đang giải phóng. Thử lại sau.')
                camera = camera_factory(body.profile)
                app.state.camera = camera
                profile = body.profile
                events.clear()
                if running:
                    await asyncio.to_thread(camera.start)
        return snapshot()

    @app.get('/api/camera/frame')
    async def frame(landmarks: bool = True):
        data = await asyncio.to_thread(camera.frame, landmarks)
        if data is None:
            raise HTTPException(503, camera.error or 'Chưa có hình camera.')
        return Response(data, media_type='image/jpeg')

    @app.post('/api/events/clear')
    async def clear():
        snapshot()
        events.clear()
        return snapshot()

    @app.post('/api/trial')
    async def evaluate(body: Trial):
        nonlocal trial
        if trial or capture or not camera.running or not camera.model_ready:
            raise HTTPException(409, 'Cần camera và model sẵn sàng, không có lượt thử đang chạy.')
        if body.label is not None and body.label not in (camera.info or {}).get('classes', {}):
            raise HTTPException(422, 'Nhãn này không có trong model đang chọn.')
        # Drain events captured before this trial; never count them as its outcome.
        snapshot()
        began = monotonic()
        trial = {'id': uuid4().hex, 'label': body.label, 'started': began, 'ends': began + 10, 'events': [], 'frames': camera.frame_count}
        return snapshot()

    @app.post('/api/capture')
    async def collect(body: Capture):
        nonlocal capture, last_capture
        async with lifecycle:
            snapshot()
            if trial or capture or not camera.running or not camera.model_ready:
                raise HTTPException(409, 'Cần camera/model sẵn sàng, không có lượt thử hoặc thu mẫu đang chạy.')
            vocabulary = set().union(*(set(s['classes']) for s in model_schemas().values()))
            if (body.kind == 'gesture' and body.label not in vocabulary) or (body.kind != 'gesture' and body.label is not None):
                raise HTTPException(422, 'Chọn nhãn checkpoint hợp lệ hoặc để trống cho mẫu âm.')
            if not hasattr(camera, 'begin_capture'):
                raise HTTPException(503, 'Camera chưa hỗ trợ thu landmarks benchmark.')
            checkpoint_path(profile)
            started = monotonic() + 2
            capture = {'started': started, 'ends': started + 10,
                       'metadata': {**body.model_dump(), 'id': uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
                                    'preprocessing': model_schemas()['new']['preprocessing'], 'profile_at_capture': profile}}
            last_capture = None
            camera.begin_capture(started, capture['ends'])
        return snapshot()

    @app.post('/api/shutdown')
    async def shutdown():
        if app.state.shutdown:
            app.state.shutdown()
        return {'stopping': True}

    @app.get('/')
    async def home():
        return FileResponse(ROOT / 'model_test/index.html')

    @app.get('/api/benchmark/report')
    async def report():
        path = ROOT / '.tools/model-benchmark/latest/report.md'
        if not path.is_file():
            raise HTTPException(404, 'Chạy run_model_benchmark.bat để tạo báo cáo trước.')
        return FileResponse(path, media_type='text/plain; charset=utf-8')

    @app.get('/ui/frame-presenter.mjs')
    async def presenter():
        return FileResponse(ROOT / 'shared/camera/presenter.mjs', media_type='text/javascript')

    app.mount('/ui', StaticFiles(directory=ROOT / 'model_test'), name='model-test-ui')
    app.mount('/theme', StaticFiles(directory=ROOT / 'shared/styles'), name='model-test-theme')
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='new')
    parser.add_argument('--port', type=int, default=5173)
    parser.add_argument('--camera-index', type=int, default=0)
    parser.add_argument('--session', default=uuid4().hex)
    args = parser.parse_args()
    os.environ['DAKT_CAMERA_INDEX'] = str(args.camera_index)
    application = create_test_app(args.profile, session=args.session)
    server = uvicorn.Server(uvicorn.Config(application, host='127.0.0.1', port=args.port, workers=1, access_log=False))
    application.state.shutdown = lambda: setattr(server, 'should_exit', True)
    server.run()
