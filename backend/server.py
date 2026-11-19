"""One shared backend. Run with one worker so the camera has one owner."""
import asyncio
from base64 import b64decode
from binascii import Error as Base64Error
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from course_training import CourseTraining, ID, MAX_PACKAGE
from gesture_learning import GestureLearning
from pydantic import BaseModel, Field
from recognition_service import CameraService
from text_composition import compose_sign
from pi_modes import PiModes
from pi_microphone import PiMicrophone
from lan_discovery import LANDiscovery, discovery_proof
from sign_vocabulary import VOCABULARY

ROOT = Path(__file__).resolve().parent


class Command(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=0)
    action: Literal['set', 'append', 'space', 'backspace', 'clear']
    text: str = Field(default='', max_length=2000)


class Message(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    kind: Literal['text', 'speech', 'sign', 'conversation'] = 'text'
    text: str = Field(min_length=1, max_length=2000)
    transcript: str = Field(default='', max_length=2000)


class PiMode(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    epoch: str = Field(min_length=1, max_length=80)
    mode: Literal['iot', 'ai']


class PiDraft(PiMode):
    text: str = Field(max_length=2000)
    expected_revision: int = Field(ge=0)


Voice = Literal['Aoede', 'Kore', 'cit-ngoc-huyen']


class SpeakerSettings(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    volume: int | None = Field(default=None, ge=0, le=100, strict=True)
    gain_db: int | None = Field(default=None, ge=-12, le=6, strict=True)
    muted: bool | None = Field(default=None, strict=True)
    allow_offline: bool | None = Field(default=None, strict=True)
    voice: Voice | None = None
    speed: int | None = Field(default=None, ge=80, le=120, strict=True)


class VoicePreview(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    epoch: str = Field(min_length=1, max_length=80)
    voice: Voice
    speed: int = Field(ge=80, le=120, strict=True)
    text: str | None = Field(default=None, max_length=500)


class SpeakerTest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    epoch: str = Field(min_length=1, max_length=80)
    kind: Literal['tone', 'offline']


class LearningSession(BaseModel):
    enabled: bool = Field(strict=True)


class LearningEvent(BaseModel):
    event: str = Field(min_length=32, max_length=32, pattern='^[0-9a-f]+$')


class LearningFeedback(LearningEvent):
    label: str = Field(min_length=1, max_length=80)


class MobileLearningFeedback(LearningFeedback):
    device_id: str = Field(pattern='^[a-f0-9]{32}$')
    session_id: str = Field(pattern='^[a-f0-9]{32}$')
    captured_at: datetime
    version: Literal[1]
    model_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    predicted: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    features: str = Field(min_length=20160, max_length=20160)


class LearningReview(BaseModel):
    action: Literal['approved', 'rejected', 'trained', 'delete']


class PiQuestion(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    epoch: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    task: Literal['auto', 'question', 'rewrite', 'search','weather'] = 'question'
    read_results: bool = False
    use_saved_location: bool = True
    location_source: Literal['phone', 'manual'] | None = None
    location: 'SearchLocation | None' = None


class SearchLocation(BaseModel):
    label: str = Field(default='', max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)


PiQuestion.model_rebuild()


class LocationRevision(BaseModel):
    request_id: str = Field(min_length=8,max_length=80)
    expected_revision: int = Field(ge=0)


class LocationSearch(BaseModel):
    name: str = Field(min_length=3,max_length=160)


class SharedLocation(LocationRevision):
    lat: float = Field(ge=-90,le=90,allow_inf_nan=False)
    lon: float = Field(ge=-180,le=180,allow_inf_nan=False)
    accuracy: float | None = Field(default=None,ge=0,le=100000,allow_inf_nan=False)
    timestamp: float = Field(ge=0,allow_inf_nan=False)
    source: Literal['phone','browser','manual']
    label: str = Field(default='',max_length=200)


class PiControl(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    epoch: str = Field(min_length=1, max_length=80)
    device: Literal['light', 'fan']
    value: bool = Field(strict=True)


class PiSelect(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    epoch: str = Field(min_length=1, max_length=80)
    candidate_id: str | None = Field(default=None, max_length=80)
    expected_revision: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=80)
    operation: Literal['append', 'replace_last', 'delete_last', 'append_caption'] = 'append'


class MicRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS state (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                    sentence TEXT NOT NULL, transcript TEXT NOT NULL, sentence_revision INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO state(id,revision,sentence,transcript) VALUES(1,0,'','');
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    text TEXT NOT NULL, transcript TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
            ''')
            if 'sentence_revision' not in {row['name'] for row in db.execute('PRAGMA table_info(state)')}:
                db.execute('ALTER TABLE state ADD COLUMN sentence_revision INTEGER NOT NULL DEFAULT 0')
                db.execute('UPDATE state SET sentence_revision=revision')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.create_function('casefold', 1, str.casefold)
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self):
        with self.connect() as db:
            state = dict(db.execute('SELECT revision,sentence_revision,sentence,transcript FROM state WHERE id=1').fetchone())
            state['history_count'] = db.execute('SELECT COUNT(*) FROM history').fetchone()[0]
            return state

    def mutate(self, operation, payload):
        fingerprint = hashlib.sha256((operation + json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM operations WHERE id=?', (payload['request_id'],)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Mã yêu cầu đã được dùng cho nội dung khác.')
                return json.loads(previous['result'])
            state = dict(db.execute('SELECT * FROM state WHERE id=1').fetchone())
            if operation == 'command':
                if payload['expected_revision'] != state['sentence_revision']:
                    raise HTTPException(409, 'Nội dung đã thay đổi trên thiết bị khác. Hãy kiểm tra và thử lại.')
                action, text, sentence = payload['action'], payload['text'], state['sentence']
                if action == 'set':
                    sentence = text
                elif action == 'append':
                    sentence += text
                elif action == 'space':
                    sentence += ' ' if sentence and not sentence.endswith(' ') else ''
                elif action == 'backspace':
                    sentence = sentence[:-1]
                else:
                    sentence = ''
                if len(sentence) > 2000:
                    raise HTTPException(422, 'Câu vượt quá 2000 ký tự.')
                db.execute('UPDATE state SET sentence=?,revision=revision+1,sentence_revision=sentence_revision+1 WHERE id=1', (sentence,))
                result = {'ok': True}
            else:
                text = payload['text'].strip()
                if not text:
                    raise HTTPException(422, 'Nội dung không được để trống.')
                created = datetime.now(timezone.utc).isoformat()
                cursor = db.execute('INSERT INTO history(kind,text,transcript,created_at) VALUES(?,?,?,?)',
                                    (payload['kind'], text, payload['transcript'], created))
                if payload['kind'] == 'speech':
                    db.execute('UPDATE state SET transcript=?,revision=revision+1 WHERE id=1', (text,))
                else:
                    db.execute('UPDATE state SET revision=revision+1 WHERE id=1')
                result = {'ok': True, 'id': cursor.lastrowid}
            result['revision'] = db.execute('SELECT revision FROM state WHERE id=1').fetchone()[0]
            db.execute('INSERT INTO operations VALUES(?,?,?)', (payload['request_id'], fingerprint, json.dumps(result)))
            return result

    def history(self, query, limit, offset):
        with self.connect() as db:
            pattern = query.casefold()
            condition = 'instr(casefold(text),?)>0 OR instr(casefold(transcript),?)>0'
            total = db.execute(f'SELECT COUNT(*) FROM history WHERE {condition}', (pattern, pattern)).fetchone()[0]
            rows = db.execute(f'SELECT * FROM history WHERE {condition} ORDER BY id DESC LIMIT ? OFFSET ?',
                              (pattern, pattern, limit, offset)).fetchall()
            return {'items': [dict(row) for row in rows], 'total': total}

    def delete(self, item_id):
        with self.connect() as db:
            cursor = db.execute('DELETE FROM history WHERE id=?', (item_id,))
            if cursor.rowcount:
                db.execute('UPDATE state SET revision=revision+1 WHERE id=1')


def create_app(db_path=None):
    store = Store(db_path or os.getenv('DAKT_DB', ROOT / 'data' / 'communication.sqlite3'))
    token = os.getenv('DAKT_API_TOKEN', '')
    allow_delete = os.getenv('DAKT_ALLOW_DELETE', 'true').lower() == 'true'
    camera = CameraService(ROOT)
    learning = GestureLearning(store)
    training = CourseTraining(store, learning, camera)
    pi = PiModes(store)
    microphone = PiMicrophone()
    discovery = LANDiscovery()
    clients = set()
    confirmed_sign = None

    def authorized(authorization):
        return not token or secrets.compare_digest(authorization.encode(), ('Bearer ' + token).encode())

    async def require_auth(request: Request):
        if not authorized(request.headers.get('authorization', '')):
            raise HTTPException(401, 'Mã truy cập không đúng hoặc chưa được nhập.')

    async def require_training_auth(request: Request):
        if not token:
            raise HTTPException(503, 'Cần cấu hình mã truy cập trên Pi để quản lý huấn luyện.')
        await require_auth(request)

    training_auth = [Depends(require_training_auth)]

    def refresh_learning_visibility():
        visible = camera.running and camera.recognition.get('status') in ('recognized', 'stabilizing', 'uncertain')
        if not visible:
            learning.live = None
        return visible

    def snapshot():
        refresh_learning_visibility()
        return {**store.snapshot(), 'camera': camera.status(), 'ai': camera.ai_status(),
                'capabilities': {'history_delete': allow_delete, 'smart_home': False, 'stt': 'client', 'tts': 'client'},
                'recognition': camera.recognition, 'confirmed_sign': confirmed_sign, 'pi': pi.snapshot(),
                'microphone': microphone.state, 'discovery': discovery.status(),
                'learning': {'session': learning.session, 'candidate': learning.candidate()}}

    async def broadcast():
        packet = {'type': 'state', 'state': snapshot()}
        async def send(ws):
            try:
                await asyncio.wait_for(ws.send_json(packet), timeout=2)
            except Exception:
                clients.discard(ws)
        await asyncio.gather(*(send(ws) for ws in tuple(clients)))

    async def monitor():
        nonlocal confirmed_sign
        last_serial = -1
        last_pi = -1
        last_mic = -1
        while True:
            await asyncio.sleep(.25)
            pi.tick()
            if camera.serial != last_serial:
                last_serial = camera.serial
                result = camera.take_result()
                if result:
                    if refresh_learning_visibility():
                        learning.observe(result, camera.model_info)
                    pi.sign(result)
                    if not result.get('confirmed', True):
                        await broadcast()
                        continue
                    if pi.enabled:
                        confirmed_sign = {'id':result['id'], 'source':'sign_confirmed', 'text':result['text'],
                                          'sentence':pi.buffers['ai']['text'], 'speakable':len(result['text'].strip())>1}
                        await broadcast()
                        continue
                    state = store.snapshot()
                    try:
                        sentence = compose_sign(state['sentence'], result['label'], result['text'])
                        store.mutate('command', {'request_id': 'sign-' + result['id'],
                                     'expected_revision': state['sentence_revision'], 'action': 'set', 'text': sentence})
                        if sentence != state['sentence']:
                            confirmed_sign = {'id': result['id'], 'source': 'sign_confirmed',
                                              'text': result['text'], 'sentence': sentence,
                                              'speakable': len(result['text'].strip()) > 1}
                    except HTTPException:
                        camera.error = 'Câu đã đủ 2000 ký tự. Lưu và xóa câu để tiếp tục.'
                await broadcast()
            elif pi.version != last_pi or microphone.version != last_mic:
                await broadcast()
            last_pi = pi.version
            last_mic = microphone.version

    @asynccontextmanager
    async def lifespan(app):
        discovery.start()
        pi.mqtt.start(pi.on_status)
        task = asyncio.create_task(monitor())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(camera.stop)
        await microphone.close()
        await pi.stop()
        await asyncio.to_thread(discovery.stop)

    app = FastAPI(title='DAKT-Nc · Giao tiếp', version='2.0.0', lifespan=lifespan)
    origins = [x.strip() for x in os.getenv('DAKT_CORS_ORIGINS',
               'http://localhost,http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,capacitor://localhost,https://localhost').split(',') if x.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET','POST','DELETE'],
                       allow_headers=['Authorization','Content-Type'])

    @app.get('/api/training/status', dependencies=training_auth)
    async def training_status():
        return training.status()

    @app.post('/api/training/prepare', dependencies=training_auth)
    async def training_prepare():
        return training.prepare()

    @app.post('/api/training/jobs/{job}/start', dependencies=training_auth)
    async def training_start(job: str):
        training.start(job)
        return {}

    @app.post('/api/training/jobs/{job}/reset', dependencies=training_auth)
    async def training_reset(job: str):
        training.reset(job)
        return {}

    @app.get('/api/training/jobs/{job}/dataset', dependencies=training_auth)
    async def training_dataset(job: str):
        return FileResponse(training.job_path(job) / 'dataset.json', filename=f'deafy-{job}.json',
                            headers={'Cache-Control': 'no-store'})

    @app.post('/api/training/agent/{agent}', dependencies=training_auth)
    async def training_poll(agent: str):
        if not ID.fullmatch(agent):
            raise HTTPException(422, 'Mã laptop không hợp lệ.')
        return {'job': training.poll(agent)}

    @app.post('/api/training/jobs/{job}/progress', dependencies=training_auth)
    async def training_progress(job: str, agent: str, epoch: int, failed: bool = False):
        training.agent_update(job, agent, epoch, failed)
        return {}

    @app.post('/api/training/jobs/{job}/import', dependencies=training_auth)
    async def training_import(job: str, request: Request, agent: str = None):
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_PACKAGE:
                raise HTTPException(413, 'Gói model quá lớn.')
            content.extend(chunk)
        training.import_model(job, content, agent)
        return {}

    @app.get('/api/training/versions/{version}/evaluation', dependencies=training_auth)
    async def training_evaluation(version: str):
        return training.evaluation(version)

    @app.post('/api/training/versions/{version}/{action}', dependencies=training_auth)
    async def training_action(version: str, action: str):
        if action in ('activate', 'rollback'):
            state = pi.snapshot()
            if (state['ai']['status'] == 'processing'
                    or state['speech']['status'] in ('processing', 'pending', 'ACK', 'PLAYING')):
                raise HTTPException(409, 'Pi đang xử lý AI hoặc phát loa. Hãy thử lại khi hoàn tất.')
        training.operation(version, action)
        return {}

    @app.get('/api/health')
    async def health():
        return {'service': 'DAKT-Nc', 'ready': True, 'ai': camera.ai_status(), 'auth_required': bool(token),
                'discovery': discovery.status()}

    @app.get('/api/discovery')
    async def discover(challenge: str = '', kind: str = 'api'):
        if not discovery.enabled:
            raise HTTPException(404, 'Khám phá Pi chưa bật.')
        try:
            return discovery_proof(challenge, kind)
        except (ValueError, OSError):
            raise HTTPException(400, 'Không xác minh được dịch vụ Pi.') from None

    @app.get('/api/state', dependencies=[Depends(require_auth)])
    async def get_state():
        return snapshot()

    @app.post('/api/commands', dependencies=[Depends(require_auth)])
    async def command(payload: Command):
        result = store.mutate('command', payload.model_dump())
        await broadcast()
        return {**result, 'state': snapshot()}

    @app.post('/api/history', dependencies=[Depends(require_auth)])
    async def save_message(payload: Message):
        result = store.mutate('message', payload.model_dump())
        await broadcast()
        return {**result, 'state': snapshot()}

    @app.get('/api/history', dependencies=[Depends(require_auth)])
    async def history(q: str = Query(default='', max_length=200), limit: int = Query(default=30, ge=1, le=100),
                      offset: int = Query(default=0, ge=0)):
        return store.history(q, limit, offset)

    @app.get('/api/history/{item_id}', dependencies=[Depends(require_auth)])
    async def detail(item_id: int):
        with store.connect() as db:
            row = db.execute('SELECT * FROM history WHERE id=?', (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Nội dung đã bị xóa hoặc không tồn tại.')
        return dict(row)

    @app.delete('/api/history/{item_id}', dependencies=[Depends(require_auth)])
    async def delete(item_id: int):
        if not allow_delete:
            raise HTTPException(403, 'Máy chủ không cho phép xóa lịch sử.')
        store.delete(item_id)
        await broadcast()
        return {'ok': True}

    @app.post('/api/camera/start', dependencies=[Depends(require_auth)])
    async def start_camera():
        await asyncio.to_thread(camera.start)
        await broadcast()
        return snapshot()

    @app.post('/api/camera/stop', dependencies=[Depends(require_auth)])
    async def stop_camera():
        await asyncio.to_thread(camera.stop)
        pi.clear_caption()
        await broadcast()
        return snapshot()

    @app.get('/api/camera/frame', dependencies=[Depends(require_auth)])
    async def frame(landmarks: bool = False):
        image = await asyncio.to_thread(camera.frame, landmarks)
        if image is None:
            raise HTTPException(503, 'Camera chưa có hình. Hãy bật camera trên máy chủ.')
        return Response(image, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/api/devices', dependencies=[Depends(require_auth)])
    async def devices():
        return {'configured': False, 'items': [], 'message': 'ESP32 chỉ phát loa. Điều khiển đèn/quạt đã bị loại bỏ.'}

    @app.post('/api/pi/mode', dependencies=[Depends(require_auth)])
    async def pi_mode(payload: PiMode):
        pi.set_mode(payload.mode, payload.epoch, payload.request_id)
        await broadcast()
        return snapshot()

    @app.post('/api/pi/draft', dependencies=[Depends(require_auth)])
    async def pi_draft(payload: PiDraft):
        pi.edit(payload.model_dump())
        await broadcast()
        return snapshot()

    @app.post('/api/location/search', dependencies=[Depends(require_auth)])
    async def search_location(payload:LocationSearch):
        name=payload.name.strip()
        if len(name)<3:raise HTTPException(422,'Nhập ít nhất ba ký tự tên khu vực.')
        return await pi.location.geocode(name)

    @app.post('/api/location', dependencies=[Depends(require_auth)])
    async def update_location(payload:SharedLocation):
        pi.location.update(payload.model_dump())
        pi.version+=1
        await broadcast()
        return snapshot()

    @app.delete('/api/location', dependencies=[Depends(require_auth)])
    async def clear_location(payload:LocationRevision):
        pi.location.update(payload.model_dump(),clear=True)
        pi.version+=1
        await broadcast()
        return snapshot()

    @app.post('/api/pi/question', dependencies=[Depends(require_auth)], status_code=202)
    async def pi_question(payload: PiQuestion):
        if microphone.busy:
            raise HTTPException(409, 'Dừng nghe và chờ nhận dạng xong trước khi hỏi AI/phát loa.')
        pi.ask(payload.model_dump())
        await broadcast()
        return snapshot()

    @app.post('/api/pi/control', dependencies=[Depends(require_auth)], status_code=202)
    async def pi_control(payload: PiControl):
        pi.control(payload.epoch, payload.request_id, payload.device, payload.value)
        await broadcast()
        return snapshot()

    @app.post('/api/pi/speaker', dependencies=[Depends(require_auth)])
    async def pi_speaker(payload: SpeakerSettings):
        changes = payload.model_dump(exclude={'request_id'}, exclude_none=True)
        if not changes:
            raise HTTPException(422, 'Chọn mức âm thanh cần thay đổi.')
        pi.set_speaker(payload.request_id, changes)
        await broadcast()
        return snapshot()

    @app.post('/api/pi/speaker/preview', dependencies=[Depends(require_auth)], status_code=202)
    async def voice_preview(payload: VoicePreview):
        if microphone.busy:
            raise HTTPException(409, 'Dừng nghe và chờ nhận dạng xong trước khi phát loa.')
        sample = (payload.text or '').strip() or ('Xin chào, tôi là trợ lý Deafy. Hôm nay nhiệt độ là 28 độ C. '
                  'Bạn có thể đến số 151 đường Đồng Khởi, Quận 1. Bạn cần tôi giúp gì không?')
        pi.speak({'request_id': payload.request_id, 'epoch': payload.epoch, 'text': sample},
                 {'voice': payload.voice, 'speed': payload.speed})
        await broadcast()
        return snapshot()

    @app.post('/api/pi/speaker/test', dependencies=[Depends(require_auth)], status_code=202)
    async def speaker_test(payload: SpeakerTest):
        if microphone.busy:
            raise HTTPException(409, 'Dừng nghe và chờ nhận dạng xong trước khi phát loa.')
        sample = 'Xin chào. Đây là giọng tiếng Việt ngoại tuyến của trợ lý Deafy.'
        pi.speak({'request_id': payload.request_id, 'epoch': payload.epoch, 'text': sample}, {'kind': payload.kind})
        await broadcast()
        return snapshot()

    @app.post('/api/pi/speech', dependencies=[Depends(require_auth)], status_code=202)
    async def pi_speech(payload: PiQuestion):
        if microphone.busy:
            raise HTTPException(409, 'Dừng nghe và chờ nhận dạng xong trước khi phát loa.')
        pi.speak(payload.model_dump())
        await broadcast()
        return snapshot()

    @app.post('/api/learning/session', dependencies=[Depends(require_auth)])
    async def learning_session(payload: LearningSession):
        learning.toggle(payload.enabled)
        camera.learning_session = learning.session
        await broadcast()
        return snapshot()

    @app.post('/api/learning/feedback', dependencies=[Depends(require_auth)])
    async def learning_feedback(payload: LearningFeedback):
        refresh_learning_visibility()
        learning.confirm(payload.event, payload.label)
        await broadcast()
        return snapshot()

    @app.post('/api/learning/mobile-feedback', dependencies=[Depends(require_auth)])
    async def mobile_learning_feedback(payload: MobileLearningFeedback):
        if os.getenv('DAKT_MOBILE_FEEDBACK') != '1':
            raise HTTPException(404, 'Pi chưa bật nhận mẫu học từ điện thoại.')
        model = camera.model_info
        if not model or model['sha256'] != payload.model_sha256:
            raise HTTPException(409, 'Model trên Pi chưa sẵn sàng hoặc khác phiên bản điện thoại.')
        if payload.captured_at.utcoffset() is None or not -300 <= (datetime.now(timezone.utc) - payload.captured_at).total_seconds() <= 604800:
            raise HTTPException(422, 'Thời điểm thu mẫu không hợp lệ hoặc đã quá 7 ngày.')
        try:
            raw = b64decode(payload.features, validate=True)
        except (Base64Error, ValueError):
            raise HTTPException(422, 'Keypoints không hợp lệ.') from None
        if len(raw) != 30 * 126 * 4:
            raise HTTPException(422, 'Keypoints phải là float32 30 × 126.')
        learning.submit_mobile(payload.event, payload.predicted, payload.label, payload.confidence,
                               f'{payload.device_id}/{payload.session_id}', model, raw,
                               payload.captured_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
        return {'status': 'pending_review'}

    @app.post('/api/learning/freeze', dependencies=[Depends(require_auth)])
    async def learning_freeze(payload: LearningEvent):
        refresh_learning_visibility()
        learning.freeze(payload.event)
        return {'event': payload.event}

    @app.delete('/api/learning/freeze/{event}', dependencies=[Depends(require_auth)])
    async def learning_unfreeze(event: str):
        if learning.frozen == event:
            learning.frozen = None
        return {'event': event}

    @app.get('/api/learning/samples', dependencies=[Depends(require_auth)])
    async def learning_samples(offset: int = Query(default=0, ge=0, le=2000)):
        return learning.inventory(offset)

    @app.post('/api/learning/samples/{event}', dependencies=[Depends(require_auth)])
    async def learning_review(event: str, payload: LearningReview):
        learning.review(event, payload.action)
        return learning.inventory()

    @app.get('/api/learning/export', dependencies=[Depends(require_auth)])
    async def learning_export(backup: bool = False):
        return JSONResponse(learning.export(backup), headers={'Cache-Control': 'no-store',
                            'Content-Disposition': 'attachment; filename="gesture-samples.json"'})

    @app.get('/api/pi/vocabulary', dependencies=[Depends(require_auth)])
    async def pi_vocabulary():
        return {'items': [{'label': key, 'text': text} for key, text in VOCABULARY.items()]}

    @app.post('/api/pi/select', dependencies=[Depends(require_auth)])
    async def pi_select(payload: PiSelect):
        if payload.operation == 'append_caption' and not camera.running:
            raise HTTPException(409, 'Bật camera và nhận diện lại ký hiệu.')
        pi.select_sign(payload.model_dump())
        await broadcast()
        return snapshot()

    @app.post('/api/pi/microphone/start', dependencies=[Depends(require_auth)], status_code=202)
    async def microphone_start(payload: MicRequest):
        if pi.ai['status'] == 'processing' or pi.speech['status'] in ('processing', 'pending', 'ACK', 'PLAYING'):
            raise HTTPException(409, 'Chờ xử lý/phát loa xong trước khi bật micro.')
        microphone.start(payload.request_id)
        await broadcast()
        return snapshot()

    @app.post('/api/pi/microphone/stop', dependencies=[Depends(require_auth)])
    async def microphone_stop(payload: MicRequest):
        microphone.stop(payload.request_id)
        return snapshot()

    @app.post('/api/pi/tts/probe', dependencies=[Depends(require_auth)])
    async def pi_tts_probe():
        return pi.tts.status()

    @app.get('/api/pi/audio/{audio_id}')
    async def pi_audio(audio_id: str, ticket: str = Query(max_length=80)):
        return Response(pi.get_audio(audio_id, ticket), media_type='audio/wav', headers={'Cache-Control': 'no-store'})

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        origin = ws.headers.get('origin')
        same_origin = origin in ('http://' + ws.headers.get('host', ''), 'https://' + ws.headers.get('host', ''))
        if origin and not same_origin and origin not in origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), 5)
            if not isinstance(hello, dict) or not (authorized('Bearer ' + str(hello.get('token', ''))) or authorized(ws.headers.get('authorization', ''))):
                await ws.close(code=1008)
                return
            clients.add(ws)
            await ws.send_json({'type': 'state', 'state': snapshot()})
            while True:
                data = await asyncio.wait_for(ws.receive_text(), timeout=45)
                if data == 'ping':
                    await ws.send_json({'type': 'pong'})
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
            pass
        finally:
            clients.discard(ws)

    @app.get('/')
    async def home():
        return {'service':'DAKT-Nc','message':'Open the Pi or Android frontend.'}

    app.state.store = store
    app.state.camera = camera
    app.state.pi = pi
    app.state.microphone = microphone
    return app


app = create_app()
