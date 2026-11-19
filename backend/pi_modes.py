"""Pi-only mode routing. Never interpret question text as an actuator command."""
import asyncio
from collections import deque, OrderedDict
import json
import logging
import os
import secrets
from time import monotonic, time
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from ai_provider import AIError, create_provider
from mqtt_bridge import MQTTBridge
from pi_tts import PiTTS, adjust_wav, speaker_test_wav
from text_composition import compose_sign
from thingspeak_logger import ThingSpeakLogger
from sign_vocabulary import VOCABULARY
from speech_text import speech_excerpt, speech_text
from lan_discovery import audio_origin
from assistant import search_places, suggest_sentence, place_speech, resolve_task
from location_service import LocationService
from weather import WeatherService


class PiModes:
    def __init__(self, store):
        self.store = store
        self.location = LocationService(store)
        self.weather = WeatherService()
        self.last_lookup = float('-inf')
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS speaker_settings (id INTEGER PRIMARY KEY, volume INTEGER, gain_db INTEGER, muted INTEGER)')
            db.execute('INSERT OR IGNORE INTO speaker_settings VALUES (1, 60, 0, 0)')
            db.execute('CREATE TABLE IF NOT EXISTS voice_settings (id INTEGER PRIMARY KEY, voice TEXT NOT NULL, speed INTEGER NOT NULL)')
            db.execute("INSERT OR IGNORE INTO voice_settings VALUES (1, 'Aoede', 100)")
            db.execute("UPDATE voice_settings SET voice='Aoede' WHERE voice NOT IN ('Aoede','Kore','cit-ngoc-huyen')")
            speaker = db.execute('SELECT volume,gain_db,muted FROM speaker_settings WHERE id=1').fetchone()
            voice = db.execute('SELECT voice,speed FROM voice_settings WHERE id=1').fetchone()
            db.execute('CREATE TABLE IF NOT EXISTS speaker_fallback (id INTEGER PRIMARY KEY, allowed INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO speaker_fallback VALUES (1, 0)')
            allowed = db.execute('SELECT allowed FROM speaker_fallback WHERE id=1').fetchone()['allowed']
            self.speaker = {**dict(speaker), **dict(voice), 'muted': bool(speaker['muted']), 'allow_offline': bool(allowed)}
            db.execute('CREATE TABLE IF NOT EXISTS pi_drafts (mode TEXT PRIMARY KEY, text TEXT NOT NULL)')
            self.buffers = {mode: {'text': '', 'revision': 0} for mode in ('iot', 'ai')}
            for row in db.execute('SELECT mode,text FROM pi_drafts'):
                if row['mode'] in self.buffers:
                    self.buffers[row['mode']]['text'] = row['text']
        self.enabled = True
        self.instance = uuid4().hex
        self.mode = 'ai'
        self.epoch = uuid4().hex
        self.mode_stamp = int(time() * 1000)
        self.version = 0
        self.accept_after = 0
        self.provider = None
        self.provider_error = ''
        try:
            self.provider = create_provider()
        except AIError as exc:
            self.provider_error = str(exc)
        self.mqtt = MQTTBridge()
        self.tts = PiTTS()
        self.telemetry = ThingSpeakLogger()
        self.ai = {'status': 'idle', 'question': '', 'answer': '', 'error': '', 'request_id': None}
        self.iot = {'status': 'idle', 'error': '', 'request_id': None}
        self.speech = {'status': 'idle', 'error': '', 'request_id': None}
        self.devices = {'light': None, 'fan': None}
        self.pending = {}
        self.requests = {}
        self.sign_ids = deque(maxlen=128)
        self.fan_prefix = None
        self.task = None
        self.audio = None
        self.wav_cache = OrderedDict()
        self.synced_epoch = None
        self.last_transport_state = None
        self.suggestion = None
        self.caption = None
        self.last_selection = None
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS recognition_corrections (request_id TEXT PRIMARY KEY, event_id TEXT, predicted TEXT, confidence REAL, selected TEXT, operation TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')

    def snapshot(self):
        return {'assistant_version': 1, 'auto_routing': True, 'iot_disabled': True, 'enabled': self.enabled, 'instance': self.instance, 'mode': self.mode, 'epoch': self.epoch, 'version': self.version,
                'buffers': self.buffers, 'settling': monotonic() < self.accept_after,
                'provider': self.provider.name if self.provider else 'unavailable',
                'provider_state': self.provider.status() if hasattr(self.provider, 'status') else None,
                'provider_error': self.provider_error, 'ai': self.ai, 'iot': self.iot, 'location': self.location.snapshot(),
                'speech': self.speech, 'speaker': self.speaker, 'voices': self.tts.voices(), 'devices': self.devices,
                'mqtt': {'connected': self.mqtt.connected, 'message': self.mqtt.error}, 'tts': self.tts.status(),
                'telemetry': self.telemetry.status(), 'suggestion': self.suggestion, 'last_selection': self.last_selection,
                'caption': self.current_caption()}

    def current_caption(self):
        if self.caption:
            remaining = int((self.caption['expires'] - monotonic()) * 1000)
            if remaining > 0:
                return {key: self.caption[key] for key in ('id', 'label', 'text', 'confidence')} | {'remaining_ms': remaining}

    def clear_caption(self):
        if self.caption:
            self.caption = None
            self.version += 1

    def set_speaker(self, request_id, changes):
        if 'voice' in changes:
            self.check_voice(changes['voice'])
        if not self.once(request_id, ['speaker', changes]):
            return
        settings = {**self.speaker, **changes}
        try:
            with self.store.connect() as db:
                db.execute('UPDATE speaker_settings SET volume=:volume,gain_db=:gain_db,muted=:muted WHERE id=1', settings)
                db.execute('UPDATE voice_settings SET voice=:voice,speed=:speed WHERE id=1', settings)
                db.execute('UPDATE speaker_fallback SET allowed=:allow_offline WHERE id=1', settings)
        except Exception:
            self.requests.pop(request_id, None)
            raise
        self.speaker = settings
        self.version += 1

    def check(self, epoch, mode=None):
        if not self.enabled or epoch != self.epoch or (mode and mode != self.mode):
            raise HTTPException(409, 'Chế độ đã thay đổi. Kiểm tra chế độ đang hoạt động rồi thử lại.')

    def once(self, request_id, payload):
        fingerprint = json.dumps(payload, sort_keys=True)
        if request_id in self.requests:
            if self.requests[request_id] != fingerprint:
                raise HTTPException(409, 'Mã yêu cầu đã được dùng với nội dung khác.')
            return False
        if len(self.requests) >= 512:
            self.requests.pop(next(iter(self.requests)))
        self.requests[request_id] = fingerprint
        return True

    def set_mode(self, mode, epoch, request_id):
        if mode != 'ai':
            raise HTTPException(410, 'Điều khiển IoT đã bị loại bỏ. ESP32 chỉ phát loa.')
        if not self.once(request_id, ['mode', mode, epoch]):
            return
        if epoch != self.epoch:
            self.requests.pop(request_id, None)
            raise HTTPException(409, 'Chế độ đã thay đổi trên thiết bị khác. Hãy thử lại.')
        if self.enabled and mode == self.mode:
            return
        self.enabled = True
        self.mode = mode
        self.epoch = uuid4().hex
        self.mode_stamp = max(self.mode_stamp + 1, int(time() * 1000))
        # A GRU window spans 3 seconds; discard windows crossing the mode boundary.
        self.accept_after = monotonic() + 3
        self.fan_prefix = None
        self.suggestion = None
        self.clear_caption()
        if self.task:
            self.task.cancel()
        if self.ai['status'] == 'processing':
            self.ai.update(status='cancelled', error='Đã dừng yêu cầu do chuyển chế độ; câu hỏi vẫn được giữ.')
        if self.speech['status'] == 'processing':
            self.speech.update(status='cancelled', error='Đã dừng tạo giọng nói do chuyển chế độ.')
        for channel in ('iot', 'speech'):
            if channel in self.pending:
                if channel == 'iot':
                    self.devices[self.pending[channel]['packet']['device']] = None
                getattr(self, channel).update(status='cancelled', error='Đã chuyển chế độ; phản hồi cũ sẽ được bỏ qua.')
        self.pending.clear()
        self.audio = None
        self.version += 1
        self.sync_mode()

    def sync_mode(self):
        if self.enabled and self.mqtt.connected and self.synced_epoch != self.epoch:
            try:
                self.mqtt.publish('mode', {'epoch': self.epoch, 'mode': self.mode, 'issued_at': int(time()),
                                           'mode_stamp': self.mode_stamp})
                self.synced_epoch = self.epoch
            except RuntimeError:
                pass

    def write_buffer(self, mode, text):
        if len(text) > 2000:
            raise HTTPException(422, 'Nội dung đã đủ 2000 ký tự. Xóa bớt để tiếp tục.')
        self.buffers[mode]['text'] = text
        self.buffers[mode]['revision'] += 1
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO pi_drafts(mode,text) VALUES(?,?)', (mode, text))
        self.version += 1

    def edit(self, payload):
        self.check(payload['epoch'], payload['mode'])
        buffer = self.buffers[payload['mode']]
        if not self.once(payload['request_id'], ['draft', payload]):
            return
        if payload['expected_revision'] != buffer['revision']:
            self.requests.pop(payload['request_id'], None)
            raise HTTPException(409, 'Có ký hiệu mới. Bản nháp vẫn được giữ; bấm Cập nhật để thay thế.')
        self.write_buffer(payload['mode'], payload['text'])

    def sign(self, result):
        if not self.enabled or monotonic() < self.accept_after or result['id'] in self.sign_ids:
            return
        if result.get('captured_at', monotonic()) < self.accept_after:
            return
        self.sign_ids.append(result['id'])
        label = result['label'].lower()
        if self.mode == 'ai':
            stable = result.get('confirmed', True)
            text = result.get('text', '').strip()
            if stable and label in VOCABULARY and text:
                self.caption = {'id': result['id'], 'label': label, 'text': text, 'confidence': result.get('confidence'),
                                'expires': result.get('captured_at', monotonic()) + 10}
                self.version += 1
            if label in VOCABULARY and (stable or not self.suggestion or self.suggestion['label'] != label):
                self.suggestion = {'id': result['id'], 'label': label, 'text': VOCABULARY[label], 'confidence': result.get('confidence'),
                                   'candidates': [item for item in result.get('candidates', []) if item.get('label') in VOCABULARY][:3]}
                self.version += 1
            return
    def select_sign(self, payload):
        self.check(payload['epoch'], 'ai')
        if not self.once(payload['request_id'], ['select', payload]):
            return
        operation = payload.get('operation', 'append')
        if operation == 'append_caption':
            caption = self.current_caption()
            buffer = self.buffers['ai']
            if (not caption or caption['id'] != payload['candidate_id'] or caption['label'] != payload['label']
                    or payload['expected_revision'] != buffer['revision']):
                self.requests.pop(payload['request_id'], None)
                raise HTTPException(409, 'Phụ đề đã hết hạn, đã chọn hoặc câu đã thay đổi.')
            before = buffer['text'].rstrip()
            try:
                self.write_buffer('ai', ' '.join(part for part in (before, caption['text']) if part))
            except HTTPException:
                self.requests.pop(payload['request_id'], None)
                raise
            self.last_selection = {'label': caption['label'], 'start': len(before), 'revision': buffer['revision']}
            if self.suggestion and self.suggestion['id'] == caption['id']:
                self.suggestion = None
            self.clear_caption()
            return
        candidate = self.suggestion['id'] if self.suggestion else None
        if payload['candidate_id'] != candidate or payload['expected_revision'] != self.buffers['ai']['revision']:
            self.requests.pop(payload['request_id'], None)
            raise HTTPException(409, 'Ký hiệu hoặc câu đã thay đổi. Kiểm tra rồi chọn lại.')
        if payload['label'] not in VOCABULARY:
            self.requests.pop(payload['request_id'], None)
            raise HTTPException(422, 'Ký hiệu này không có trong bộ nhãn hiện tại.')
        before = self.buffers['ai']['text']
        if operation != 'append':
            selected = self.last_selection
            if not selected or selected['revision'] != self.buffers['ai']['revision']:
                self.requests.pop(payload['request_id'], None)
                raise HTTPException(409, 'Câu đã được chỉnh sửa. Hãy sửa trực tiếp trong ô văn bản.')
            base = before[:selected['start']].rstrip()
        else:
            base = before
        text = base if operation == 'delete_last' else compose_sign(base, payload['label'], VOCABULARY[payload['label']])
        try:
            self.write_buffer('ai', text)
        except HTTPException:
            self.requests.pop(payload['request_id'], None)
            raise
        with self.store.connect() as db:
            db.execute('INSERT INTO recognition_corrections(request_id,event_id,predicted,confidence,selected,operation) VALUES(?,?,?,?,?,?)',
                       (payload['request_id'], candidate, self.suggestion['label'] if self.suggestion else None,
                        self.suggestion.get('confidence') if self.suggestion else None, payload['label'], operation))
        self.last_selection = None if operation == 'delete_last' else {
            'label': payload['label'], 'start': len(base), 'revision': self.buffers['ai']['revision']}
        self.suggestion = None
        if self.caption and self.caption['id'] == candidate:
            self.clear_caption()
        self.version += 1

    def send(self, channel, request_id, body):
        if channel != 'speech':
            raise HTTPException(410, 'Điều khiển relay đã bị vô hiệu hóa.')
        now = time()
        packet = {'request_id': request_id, 'epoch': self.epoch, 'mode': self.mode,
                  'issued_at': int(now), 'expires_at': int(now + 8), **body}
        target = getattr(self, channel)
        target.update(status='pending', error='', request_id=request_id)
        self.pending[channel] = {'packet': packet, 'deadline': monotonic() + 8}
        self.version += 1
        try:
            self.sync_mode()
            self.mqtt.publish('command' if channel == 'iot' else 'speech', packet)
        except RuntimeError as exc:
            self.pending.pop(channel, None)
            target.update(status='error', error=str(exc))

    def control(self, epoch, request_id, device, value):
        raise HTTPException(410, 'Điều khiển IoT đã bị loại bỏ. ESP32 chỉ phát loa.')

    def ask(self, payload):
        self.check(payload['epoch'], 'ai')
        if not payload['text'].strip():
            raise HTTPException(422, 'Nhập hoặc ghép câu hỏi trước khi gửi.')
        if not self.once(payload['request_id'], ['ask', payload]):
            return
        if self.ai['status'] == 'processing' or self.speech['status'] == 'processing' or 'speech' in self.pending:
            self.requests.pop(payload['request_id'], None)
            raise HTTPException(409, 'Đang xử lý hoặc phát câu trả lời trước. Hãy chờ hoặc chuyển chế độ.')
        task = resolve_task(payload['text'], payload.get('task', 'question'))
        try:
            source = payload.get('location_source')
            if task == 'search' and os.getenv('DAKT_PLACE_PROVIDER') == 'geoapify':
                source = 'phone'
            location = self.location.resolve(payload.get('location'), payload.get('use_saved_location', True), source) if task in ('search','weather') else None
        except HTTPException:
            self.requests.pop(payload['request_id'],None)
            raise
        if not self.provider and task not in ('search','weather'):
            raise HTTPException(503, self.provider_error)
        if task in ('search','weather'):
            if source and not location:
                self.requests.pop(payload['request_id'], None)
                detail = ('GPS chưa khả dụng, sai số quá lớn hoặc đã hết hạn. Mở Cài đặt trên iPhone và chia sẻ lại vị trí.'
                          if source == 'phone' else 'Vị trí tham chiếu đã hết hạn hoặc chưa được lưu. Hãy cập nhật trong Cài đặt.')
                raise HTTPException(422, detail)
            if monotonic()-self.last_lookup<2:
                self.requests.pop(payload['request_id'],None)
                raise HTTPException(429,'Chờ hai giây trước khi tìm dữ liệu vị trí tiếp.')
            self.last_lookup=monotonic()
        self.store.mutate('message', {'request_id': 'ai-question-' + payload['request_id'],
                                     'kind': 'ai_question', 'text': payload['text'].strip(), 'transcript': ''})
        self.ai.update(status='processing', question=payload['text'].strip(), answer='', error='', request_id=payload['request_id'],
                       task=task, source=payload['text'], proposal='', search=None)
        self.speech.update(status='idle', error='', request_id=None)
        self.version += 1
        self.task = asyncio.create_task(self.answer(payload['text'].strip(), self.epoch, payload['request_id'], task, location, payload.get('read_results', False)))

    def check_voice(self, voice):
        if not any(item['id'] == voice and item['available'] for item in self.tts.voices()):
            raise HTTPException(409, 'Giọng này chưa được cấu hình trên Pi.')

    def speak(self, payload, preview=None):
        self.check(payload['epoch'], 'ai')
        if not payload['text'].strip():
            raise HTTPException(422, 'Nhập văn bản trước khi phát qua ESP32.')
        if preview and not preview.get('kind'):
            self.check_voice(preview['voice'])
        if preview:
            if self.speaker['muted'] or not self.speaker['volume']:
                raise HTTPException(409, 'Bật tiếng và tăng âm lượng trước khi nghe thử.')
        if not self.once(payload['request_id'], ['speak', payload, preview]):
            return
        if self.ai['status'] == 'processing' or self.speech['status'] == 'processing' or 'speech' in self.pending:
            self.requests.pop(payload['request_id'], None)
            raise HTTPException(409, 'Đang xử lý hoặc phát âm thanh trước. Hãy chờ rồi thử lại.')
        self.speech.update(status='processing', error='', request_id=payload['request_id'], voice=None, engine=None,
                           fallback_reason='', synthesis_ms=None, playing_ms=None)
        self.version += 1
        self.task = asyncio.create_task(self.speak_text(payload['text'].strip(), self.epoch, payload['request_id'], preview, True))

    async def prepare_speech(self, text, epoch, request_id, preview=None, verbatim=False):
        if not self.mqtt.connected:
            raise RuntimeError(self.mqtt.error)
        settings = self.speaker
        kind = preview.get('kind') if preview else None
        voice = preview['voice'] if preview and not kind else settings['voice']
        speed = preview.get('speed', settings['speed']) if preview else settings['speed']
        if epoch != self.epoch:
            return
        base = audio_origin()
        parsed = urlparse(base)
        if parsed.scheme != 'http' or not parsed.hostname or parsed.hostname in ('localhost', '127.0.0.1') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError('Cấu hình DAKT_AUDIO_BASE_URL bằng HTTP LAN của Pi để ESP lấy WAV.')
        plain = text if verbatim else speech_text(text)
        started = monotonic()

        def render():
            cache_key = (plain,voice,speed,settings['volume'],settings['gain_db'],settings['muted'],kind,settings['allow_offline'])
            cached = self.wav_cache.get(cache_key)
            if cached and monotonic()-cached[0]<300:
                self.wav_cache.move_to_end(cache_key)
                return cached[1]
            engine, actual_voice, reason = 'Gemini TTS', voice, ''
            if kind == 'tone':
                audio = speaker_test_wav()
                engine, actual_voice = 'PCM trên Pi', 'Âm kiểm tra loa'
            elif kind == 'offline':
                audio = self.tts.offline(plain, speed)
                engine, actual_voice = 'eSpeak NG', 'vi+f3'
            else:
                try:
                    if voice == 'cit-ngoc-huyen':
                        engine, actual_voice = 'CIT Voice Studio', 'Ngọc Huyền'
                        audio = self.tts.synthesize_cit(plain, speed)
                    else:
                        audio = self.tts.synthesize_cloud(plain, voice, speed)
                except RuntimeError as issue:
                    if preview or voice == 'cit-ngoc-huyen' or not settings['allow_offline']:
                        raise
                    reason = str(issue)
                    try:
                        audio = self.tts.offline(plain, speed)
                    except RuntimeError as offline_issue:
                        raise RuntimeError(f'{reason} {offline_issue}') from None
                    engine, actual_voice = 'eSpeak NG', 'vi+f3'
            wav = adjust_wav(audio, settings['volume'], settings['gain_db'], settings['muted'])
            result = wav, engine, actual_voice, reason
            if not reason:
                self.wav_cache[cache_key] = (monotonic(),result)
                while len(self.wav_cache)>3 or sum(len(entry[1][0]) for entry in self.wav_cache.values())>8_000_000:
                    self.wav_cache.popitem(last=False)
            return result

        wav, engine, actual_voice, reason = await asyncio.to_thread(render)
        if epoch != self.epoch:
            return
        audio_id, ticket = uuid4().hex, secrets.token_urlsafe(24)
        self.audio = {'id': audio_id, 'ticket': ticket, 'wav': wav, 'expires': monotonic() + 120}
        self.speech.update(voice=actual_voice, engine=engine, fallback_reason=reason)
        self.speech['synthesis_ms'] = round((monotonic() - started) * 1000)
        logging.getLogger('uvicorn.error').info('Audio generated: engine=%s voice=%s request=%s', engine, actual_voice, request_id)
        self.send('speech', request_id, {'audio_url': f'{base}/api/pi/audio/{audio_id}?ticket={ticket}'})
        if 'speech' in self.pending:
            self.pending['speech']['started'] = started
            self.pending['speech']['wav_size'] = len(wav)

    async def speak_text(self, text, epoch, request_id, preview=None, verbatim=False):
        try:
            await self.prepare_speech(text, epoch, request_id, preview, verbatim)
        except asyncio.CancelledError:
            return
        except Exception as issue:
            if epoch == self.epoch:
                self.speech.update(status='error', error=str(issue) if isinstance(issue, RuntimeError) else 'Không tạo được âm thanh trên Pi.')
        finally:
            self.version += 1

    async def answer(self, question, epoch, request_id, task='question', location=None, read_results=False):
        try:
            result = None
            if task == 'search':
                result = await asyncio.wait_for(search_places(question, location, self.provider), 45)
                text = place_speech(result['items'],result) or result['message']
            elif task == 'weather':
                result = await asyncio.wait_for(self.weather.get(location),12)
                text = result['message']
            elif task == 'rewrite':
                text = await asyncio.wait_for(suggest_sentence(self.provider, question), 35)
            else:
                text = await asyncio.wait_for(self.provider.answer(question), 35)
            if epoch != self.epoch or self.ai['request_id'] != request_id:
                return
            provider = 'open-meteo' if task == 'weather' else 'maps' if task == 'search' else getattr(self.provider, 'active_provider', getattr(self.provider, 'name', 'unavailable'))
            speech = place_speech(result['items'],result) if task=='search' and result else (
                result.get('speech_text',text) if task=='weather' and result else speech_excerpt(text) if task=='question' else '')
            self.ai.update(display_text=text,speech_text=speech,task_type=task,
                           results=result,source=result.get('source') if result else provider)
            self.ai.update(status='done', answer=text, error='', proposal=text if task == 'rewrite' else '', search=result,
                           provider=provider)
            self.store.mutate('message', {'request_id': 'ai-answer-' + request_id,
                                         'kind': 'ai_answer', 'text': text, 'transcript': ''})
            self.version += 1
            # One server owns playback; websocket subscribers never trigger speech.
            spoken = ''
            if read_results and task == 'question' and provider in ('gemini', 'groq'):
                spoken = speech
            elif read_results and result and result['status'] == 'ok' and not result.get('stale'):
                if task == 'weather' and result.get('source') == 'Open-Meteo':
                    spoken = speech
                elif task == 'search' and result['items'] and result.get('source') in ('© OpenStreetMap contributors', 'Google Places', 'Geoapify'):
                    spoken = speech
            if spoken:
                self.speech.update(status='processing', error='', request_id=request_id, voice=None, engine=None,
                                   fallback_reason='', synthesis_ms=None, playing_ms=None)
                self.version += 1
                await self.speak_text(spoken, epoch, request_id)
        except asyncio.CancelledError:
            return
        except (AIError, TimeoutError) as issue:
            if epoch == self.epoch:
                self.ai.update(status='error', error=str(issue) if isinstance(issue, AIError) else 'AI quá thời gian chờ. Hãy gửi lại; câu gốc vẫn được giữ.')
                self.ai['provider'] = 'offline' if isinstance(issue, TimeoutError) else getattr(self.provider, 'active_provider', 'offline')
        except Exception as issue:
            if epoch == self.epoch:
                # Keep internal provider/OS errors and credentials off the wire.
                if self.ai['status'] == 'done':
                    self.speech.update(status='error', error=str(issue) if isinstance(issue, RuntimeError) else 'Không tạo được âm thanh trên Pi.')
                else:
                    self.ai.update(status='error', error='Dịch vụ AI đang lỗi. Câu hỏi vẫn được giữ; hãy thử lại.')
        finally:
            self.version += 1

    def on_status(self, packet):
        channel = packet.get('kind')
        if channel == 'hello':
            self.synced_epoch = None
            if self.pending.pop('speech', None):
                self.audio = None
                self.speech.update(status='error', error='ESP32 vừa kết nối lại. Gửi yêu cầu mới để phát.')
                self.version += 1
            return
        if channel not in ('iot', 'speech'):
            return
        pending = self.pending.get(channel)
        if not pending or packet.get('epoch') != self.epoch or packet.get('request_id') != pending['packet']['request_id']:
            return
        if monotonic() > pending['deadline'] or packet.get('mode') != self.mode:
            return
        target = getattr(self, channel)
        status = packet.get('status')
        order = {'pending': 0, 'ACK': 1, 'PLAYING': 2, 'DONE': 3, 'ERROR': 3}
        if status not in ('ACK', 'DONE', 'ERROR', 'PLAYING') or (channel == 'iot' and status == 'PLAYING'):
            return
        if order[status] < order.get(target['status'], 0):
            return
        if channel == 'iot' and status == 'DONE':
            command = pending['packet']
            if packet.get('device') != command['device'] or type(packet.get('value')) is not bool or packet['value'] != command['value']:
                return
            self.devices[command['device']] = packet['value']
        errors = {'AUDIO_NOT_CONFIGURED': 'ESP32 chưa cấu hình loa/I2S. Câu trả lời vẫn được giữ.',
                  'AUDIO_HTTP': 'ESP32 không tải được WAV từ Pi.',
                  'AUDIO_WAV': 'ESP32 nhận WAV sai định dạng hoặc kích thước.',
                  'AUDIO_STREAM': 'Luồng WAV bị gián đoạn hoặc quá hạn trên ESP32.',
                  'AUDIO_I2S': 'ESP32 không khởi tạo hoặc ghi được dữ liệu I2S.',
                  'RELAY_NOT_CONFIGURED': 'ESP32 chưa cấu hình chân relay của thiết bị này.',
                  'CLOCK_OR_EXPIRED': 'Lệnh đã hết hạn hoặc đồng hồ ESP32 chưa đồng bộ với Pi.',
                  'AUDIO_HTTP_OR_I2S': 'ESP32 không lấy/phát được WAV. Kiểm tra HTTP LAN và chân I2S.',
                  'AUDIO_BUSY': 'ESP32 đang phát âm thanh trước. Hãy chờ rồi gửi lại.',
                  'WRONG_MODE': 'ESP32 từ chối lệnh do chế độ không khớp.'}
        if channel == 'speech' and status != target['status'] and status in ('ACK', 'PLAYING'):
            if status == 'PLAYING' and 'started' in pending:
                target['playing_ms'] = round((monotonic() - pending['started']) * 1000)
            # ESP stages clips up to 1 MiB before PLAYING. Budget extra time at 32 KiB/s.
            wav_size = pending.get('wav_size', 0)
            staged_seconds = (wav_size + 32767) // 32768 if 44 < wav_size <= 1024 * 1024 + 44 else 0
            pending['deadline'] = monotonic() + (12 + staged_seconds if status == 'ACK' else 120)
        target.update(status=status, error=errors.get(packet.get('error'), 'ESP32 báo lỗi. Kiểm tra thiết bị và kết nối.') if status == 'ERROR' else '')
        if status in ('DONE', 'ERROR'):
            self.pending.pop(channel, None)
            if channel == 'speech':
                self.audio = None
        self.version += 1

    def tick(self):
        if self.caption and not self.current_caption():
            self.clear_caption()
        self.telemetry.observe(self.mode if self.enabled else 'inactive', self.devices, self.mqtt.connected)
        self.telemetry.tick()
        transport_state = (self.mqtt.connected, self.mqtt.error, monotonic() < self.accept_after,
                           self.telemetry.entry_id, self.telemetry.error,
                           getattr(self.provider, 'active_provider', None), getattr(self.provider, 'stage', None),
                           self.location.snapshot()['status'], self.location.snapshot()['current'].get('source') if self.location.snapshot()['current'] else None)
        if transport_state != self.last_transport_state:
            self.last_transport_state = transport_state
            self.version += 1
        if not self.mqtt.connected:
            self.synced_epoch = None
        self.sync_mode()
        for channel, pending in list(self.pending.items()):
            if not self.mqtt.connected or monotonic() > pending['deadline']:
                target = getattr(self, channel)
                stage = {'pending': 'chưa xác nhận lệnh', 'ACK': 'chưa bắt đầu phát', 'PLAYING': 'chưa báo kết thúc'}.get(target['status'], 'chưa phản hồi')
                error = f'ESP32 {stage} đúng hạn.' if self.mqtt.connected else 'Pi mất kết nối MQTT trong khi chờ ESP32.'
                target.update(status='error', error=error)
                self.pending.pop(channel, None)
                if channel == 'speech':
                    self.audio = None
                self.version += 1
        if self.audio and monotonic() > self.audio['expires']:
            self.audio = None

    def get_audio(self, audio_id, ticket):
        audio = self.audio
        if not audio or audio['id'] != audio_id or monotonic() > audio['expires'] or not secrets.compare_digest(audio['ticket'], ticket):
            raise HTTPException(404, 'Âm thanh không còn khả dụng.')
        return audio['wav']

    async def stop(self):
        await self.telemetry.stop()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await asyncio.to_thread(self.mqtt.stop)
