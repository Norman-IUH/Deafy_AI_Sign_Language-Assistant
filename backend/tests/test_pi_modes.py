import asyncio
from io import BytesIO
import json
from struct import pack, unpack
from time import monotonic
from urllib.error import HTTPError, URLError
import wave

from fastapi.testclient import TestClient
import pytest

from ai_provider import AIError, GeminiProvider, MockProvider, create_provider
from server import create_app


def sample_wav(sample=10000):
    output = BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
        wav.writeframes(pack('<h', sample) * 1000)
    return output.getvalue()


class FakeMQTT:
    connected = True
    error = ''

    def __init__(self):
        self.sent = []

    def publish(self, kind, packet):
        self.sent.append((kind, packet.copy()))

    def start(self, callback):
        self.callback = callback

    def stop(self):
        pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_AI_PROVIDER', 'mock')
    monkeypatch.delenv('DAKT_API_TOKEN', raising=False)
    monkeypatch.delenv('DAKT_MQTT_HOST', raising=False)
    monkeypatch.setattr('server.ROOT', tmp_path)
    app = create_app(tmp_path / 'state.sqlite3')
    app.state.pi.mqtt = FakeMQTT()
    return app


def switch(pi, mode):
    pi.set_mode(mode, pi.epoch, 'mode-' + pi.epoch)
    pi.accept_after = 0


def sign(pi, label, text=None):
    pi.sign({'id': 'sign-' + str(pi.version), 'label': label, 'text': text or label,
             'captured_at': monotonic()})


def reply(pi, channel, status, **extra):
    pending = pi.pending[channel]['packet']
    return dict(kind=channel, status=status, request_id=pending['request_id'],
                epoch=pending['epoch'], mode=pending['mode'], **extra)


def test_legacy_control_rejected_at_every_boundary(app):
    pi = app.state.pi
    with TestClient(app) as client:
        assert pi.enabled and pi.mode == 'ai'
        assert client.post('/api/pi/mode', json=dict(request_id='legacy-mode',epoch=pi.epoch,mode='iot')).status_code == 410
        assert client.post('/api/pi/control', json=dict(request_id='legacy-command',epoch=pi.epoch,device='light',value=True)).status_code == 410
        assert client.post('/api/pi/draft', json=dict(request_id='legacy-draft',epoch=pi.epoch,mode='iot',text='Bật đèn',expected_revision=0)).status_code == 409
        for label in ['bat_den','tat_den','mo','quat_cay']:
            sign(pi,label)
        assert not pi.pending and not any(kind == 'command' for kind,_ in pi.mqtt.sent)
        with pytest.raises(Exception):pi.send('iot','direct-old-command',dict(device='fan',value=True))
    from mqtt_bridge import MQTTBridge
    with pytest.raises(RuntimeError):MQTTBridge().publish('command',dict(device='light',value=True))


def test_drafts_survive_backend_restart_and_conflicts(app):
    pi = app.state.pi
    pi.write_buffer('ai', 'Xin chào')
    pi.write_buffer('iot', 'Bản nháp cũ được bảo toàn')
    second = create_app(app.state.store.path).state.pi
    assert {k:v['text'] for k,v in second.buffers.items()} == {k:v['text'] for k,v in pi.buffers.items()}
    assert second.enabled and second.mode == 'ai' and second.epoch != pi.epoch
    with TestClient(app) as client:
        draft=dict(request_id='draft-new-ai',epoch=pi.epoch,mode='ai',text='Câu mới',expected_revision=1)
        assert client.post('/api/pi/draft',json=draft).status_code == 200
        assert client.post('/api/pi/draft',json=draft).status_code == 200
        assert client.post('/api/pi/draft',json=dict(draft,request_id='draft-stale')).status_code == 409


def test_ai_answer_never_auto_plays_and_quota_keeps_draft(app):
    async def scenario():
        pi=app.state.pi
        pi.write_buffer('ai','Câu gốc')
        request=dict(request_id='question-new',epoch=pi.epoch,text='Xin chào')
        pi.ask(request);pi.ask(request);await pi.task
        assert pi.ai['status']=='done' and 'MOCK' in pi.ai['answer']
        assert not pi.pending and not any(kind=='speech' for kind,_ in pi.mqtt.sent)
        class Quota:
            async def answer(self,text):raise AIError('Gemini hết hạn mức')
        pi.provider=Quota();pi.ask(dict(request,request_id='question-quota'));await pi.task
        assert pi.ai['status']=='error' and pi.buffers['ai']['text']=='Câu gốc'
    asyncio.run(scenario())


def test_speech_protocol_explicit_request_tickets_and_stale_acks(app,monkeypatch):
    async def scenario():
        pi=app.state.pi;pi.tts.ready=True
        monkeypatch.setattr(pi.tts,'synthesize_cloud',lambda text, voice, speed:sample_wav())
        monkeypatch.setenv('DAKT_AUDIO_BASE_URL','http://192.168.1.164:8001')
        request=dict(request_id='speech-explicit',epoch=pi.epoch,text='Xin chào')
        pi.speak(request);pi.speak(request);await pi.task
        assert [kind for kind,_ in pi.mqtt.sent].count('speech')==1
        with wave.open(BytesIO(pi.get_audio(pi.audio['id'],pi.audio['ticket'])), 'rb') as audio:
            samples = unpack('<1000h', audio.readframes(1000))
        assert samples[0] == samples[-1] == 0 and samples[500] == 6000
        with pytest.raises(Exception):pi.get_audio(pi.audio['id'],'wrong-ticket')
        ack=reply(pi,'speech','ACK')
        pi.on_status(dict(ack,epoch='old'));assert pi.speech['status']=='pending'
        pi.on_status(ack);assert pi.speech['status']=='ACK'
        pi.on_status(reply(pi,'speech','PLAYING'));pi.on_status(ack)
        assert pi.speech['status']=='PLAYING'
        pi.on_status(reply(pi,'speech','DONE'));assert not pi.pending and pi.audio is None
        pi.on_status(dict(ack,status='ERROR'));assert pi.speech['status']=='DONE'
        assert not any(kind=='command' for kind,_ in pi.mqtt.sent)
    asyncio.run(scenario())


def test_direct_speech_error_timeout_validation(app):
    async def scenario():
        pi=app.state.pi;pi.mqtt.connected=False;pi.mqtt.error='MQTT offline'
        pi.speak(dict(request_id='speech-offline',epoch=pi.epoch,text='Xin chào'));await pi.task
        assert pi.speech['status']=='error' and pi.speech['error']=='MQTT offline'
        pi.pending['speech']={'deadline':0,'packet':{'request_id':'expired'}}
        pi.tick();assert not pi.pending and pi.speech['status']=='error'
    asyncio.run(scenario())
    with TestClient(app) as client:
        assert client.post('/api/pi/speech',json=dict(request_id='speech-empty',epoch=app.state.pi.epoch,text='  ')).status_code==422
        assert client.post('/api/pi/speech',json=dict(request_id='speech-stale',epoch='old',text='Xin chào')).status_code==409


@pytest.mark.parametrize('wav_size,ack_wait',[(0,12),(512*1024,28),(2*1024*1024,12)])
def test_speech_reconnect_releases_pending_and_audio(app,monkeypatch,wav_size,ack_wait):
    pi=app.state.pi
    monkeypatch.setattr('pi_modes.monotonic',lambda:100)
    pi.audio={'id':'test'}
    pi.send('speech','speech-test',{})
    pi.pending['speech']['wav_size']=wav_size
    assert pi.pending['speech']['deadline']==108
    pi.on_status(reply(pi,'speech','ACK'))
    assert pi.pending['speech']['deadline']==100+ack_wait
    pi.on_status({'kind':'hello'})
    assert not pi.pending and pi.audio is None and pi.speech['status']=='error'


@pytest.mark.parametrize('code,expected', [(429, 'hạn mức'), (403, 'quyền'), (404, 'Model'), (500, 'đang lỗi'), (503, 'quá tải')])
def test_gemini_errors_are_redacted(monkeypatch, code, expected):
    def fail(*args, **kwargs):
        raise HTTPError('https://secret.invalid?key=do-not-leak', code, 'do-not-leak', {}, None)
    monkeypatch.setattr('ai_provider.urlopen', fail)
    with pytest.raises(AIError) as exc:
        GeminiProvider('do-not-leak')._answer('Bật đèn?')
    assert expected in str(exc.value) and 'do-not-leak' not in str(exc.value)


def test_gemini_text_only_request_and_offline(monkeypatch):
    def response(request, timeout):
        assert request.get_header('X-goog-api-key') == 'test-only'
        payload = json.loads(request.data)
        assert 'tools' not in payload
        assert payload['contents'][0]['parts'][0]['text'] == 'Bật đèn?'
        return BytesIO(json.dumps({'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'Câu trả lời.'}]}}]}).encode())
    monkeypatch.setattr('ai_provider.urlopen', response)
    assert GeminiProvider('test-only')._answer('Bật đèn?') == 'Câu trả lời.'
    def offline(*args, **kwargs):
        raise URLError('private network detail')
    monkeypatch.setattr('ai_provider.urlopen', offline)
    with pytest.raises(AIError, match='Internet'):
        GeminiProvider('test-only')._answer('Xin chào')


def test_no_key_uses_mock_no_paid_model_fallback(monkeypatch):
    monkeypatch.setenv('DAKT_AI_PROVIDER', 'gemini')
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    assert isinstance(create_provider(), MockProvider)
    monkeypatch.setenv('GEMINI_API_KEY', 'test-only')
    monkeypatch.setenv('GEMINI_MODEL', 'paid-model')
    with pytest.raises(AIError):
        create_provider()


def test_speaker_settings_persist_and_validate(app):
    pi = app.state.pi
    with TestClient(app) as client:
        assert client.get('/api/state').json()['pi']['speaker'] == {'volume': 60, 'gain_db': 0, 'muted': False, 'voice': 'Aoede', 'speed': 100, 'allow_offline': False}
        request = {'request_id': 'speaker-settings-1', 'volume': 75, 'gain_db': 6, 'muted': True, 'speed': 85}
        assert client.post('/api/pi/speaker', json=request).status_code == 200
        assert client.post('/api/pi/speaker', json={**request, 'volume': 50}).status_code == 409
        for invalid in ({'volume': 101}, {'gain_db': -13}, {'muted': 'false'}):
            assert client.post('/api/pi/speaker', json={'request_id': 'invalid-speaker', **invalid}).status_code == 422
    from pi_modes import PiModes
    assert PiModes(pi.store).speaker == {'volume': 75, 'gain_db': 6, 'muted': True, 'voice': 'Aoede', 'speed': 85, 'allow_offline': False}


def test_pcm_gain_limits_peak_and_mute():
    from pi_tts import adjust_wav
    for volume, gain, muted, expected in [(100, 6, False, 32760), (100, 6, True, 0), (0, 6, False, 0)]:
        with wave.open(BytesIO(adjust_wav(sample_wav(30000), volume, gain, muted)), 'rb') as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (22050, 1, 2)
            samples = unpack('<1000h', audio.readframes(1000))
        assert max(samples) == expected and samples[0] == samples[-1] == 0


def test_cloud_voice_output_is_canonical_pcm(monkeypatch):
    import base64
    from pi_tts import PiTTS

    monkeypatch.delenv('DAKT_GEMINI_TTS_KEY', raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    monkeypatch.delenv('DAKT_GEMINI_TTS_USE_CHAT_KEY', raising=False)
    assert not PiTTS().gemini_key()
    monkeypatch.setenv('DAKT_GEMINI_TTS_USE_CHAT_KEY', '1')
    pcm = pack('<h', 1200) * 1000

    def open_response(request, timeout):
        assert request.get_header('X-goog-api-key') == 'test'
        voice = json.loads(request.data)['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']
        assert voice['voiceName'] in ('Aoede', 'Kore')
        return BytesIO(json.dumps({'candidates': [{'content': {'parts': [{'inlineData': {
            'mimeType': 'audio/L16;codec=pcm;rate=24000', 'data': base64.b64encode(pcm).decode(),
        }}]}}]}).encode())

    monkeypatch.setattr('pi_tts.urlopen', open_response)
    tts = PiTTS()
    for voice in ('Aoede', 'Kore'):
        with wave.open(BytesIO(tts.synthesize_cloud('Mưa & nắng', voice, 85)), 'rb') as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (24000, 1, 2)
            assert audio.readframes(1000) == pcm


def test_voice_preview_does_not_change_saved_voice(app, monkeypatch):
    pi = app.state.pi
    monkeypatch.setenv('DAKT_GEMINI_TTS_KEY', 'test')
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://192.168.1.25:8001')
    calls = []
    monkeypatch.setattr(pi.tts, 'synthesize_cloud', lambda text, voice, speed: calls.append((text, voice, speed)) or sample_wav())
    with TestClient(app) as client:
        request = {'request_id': 'preview-voice-1', 'epoch': pi.epoch, 'voice': 'Aoede', 'speed': 85, 'text': 'Xin chào.'}
        assert client.post('/api/pi/speaker/preview', json=request).status_code == 202
        assert client.post('/api/pi/speaker/preview', json=request).status_code == 202
        from time import sleep
        for _ in range(50):
            if pi.pending.get('speech'):
                break
            sleep(.02)
        assert calls == [('Xin chào.', 'Aoede', 85)] and pi.pending.get('speech')
        assert pi.speaker['voice'] == 'Aoede'


def test_saved_female_voice_and_quota_failure_do_not_publish_alternate_audio(app, monkeypatch):
    pi = app.state.pi
    monkeypatch.setenv('DAKT_GEMINI_TTS_KEY', 'test')
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://192.168.1.25:8001')
    attempted = []

    def quota(text, voice, speed):
        attempted.append((voice, speed))
        raise RuntimeError('Gemini TTS đang hết hạn mức.')

    monkeypatch.setattr(pi.tts, 'synthesize_cloud', quota)
    with TestClient(app) as client:
        saved = client.post('/api/pi/speaker', json={'request_id': 'speaker-kore-1', 'voice': 'Kore', 'speed': 95})
        assert saved.status_code == 200
        from pi_modes import PiModes
        assert PiModes(pi.store).speaker['voice'] == 'Kore'
    asyncio.run(pi.speak_text('Xin chào', pi.epoch, 'quota-error'))
    assert attempted == [('Kore', 95)]
    assert pi.speech['status'] == 'error' and 'hết hạn mức' in pi.speech['error']
    assert not pi.audio and not pi.mqtt.sent
    pi.set_speaker('allow-fallback-1', {'allow_offline': True})
    assert PiModes(pi.store).speaker['allow_offline']
    monkeypatch.setattr(pi.tts, 'offline', lambda text, speed: sample_wav())
    asyncio.run(pi.speak_text('Xin chào', pi.epoch, 'quota-fallback'))
    assert pi.speech['engine'] == 'eSpeak NG' and pi.speech['voice'] == 'vi+f3'
    assert 'hết hạn mức' in pi.speech['fallback_reason']
    assert len([kind for kind, _ in pi.mqtt.sent if kind == 'speech']) == 1


def test_cit_unavailable_reports_error_without_switching_voice(app, monkeypatch):
    pi = app.state.pi
    monkeypatch.setenv('DAKT_CIT_ENABLED', '1')
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://192.168.1.25:8001')

    def unavailable(*_args):
        raise RuntimeError('Mất kết nối CIT Voice Studio.')

    monkeypatch.setattr(pi.tts, 'synthesize_cit', unavailable)
    monkeypatch.setattr(pi.tts, 'offline', lambda *_args: pytest.fail('CIT must not switch to eSpeak'))
    pi.set_speaker('save-cit-voice', {'voice': 'cit-ngoc-huyen', 'allow_offline': True})
    asyncio.run(pi.speak_text('Xin chào', pi.epoch, 'cit-fallback'))
    assert pi.speaker['voice'] == 'cit-ngoc-huyen'
    assert pi.speech['status'] == 'error' and 'Mất kết nối CIT' in pi.speech['error']
    assert not any(kind == 'speech' for kind, _ in pi.mqtt.sent)

