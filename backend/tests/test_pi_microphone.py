import asyncio
import json
import struct
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from pi_microphone import PiMicrophone, pcm_stats
from server import create_app


def test_usb_pcm_metrics():
    assert pcm_stats(b'') is None and pcm_stats(b'\0') is None
    result = pcm_stats(struct.pack('<hhhh', -32768, 32767, 0, 0))
    assert result['peak'] == 32768 and result['clipped_percent'] == 50
    assert abs(result['dc_offset']) < 1


@pytest.mark.parametrize('engine', ['vosk', 'whisper', 'zipformer'])
def test_microphone_pipeline_is_bounded_and_deduplicates_start(tmp_path, monkeypatch, engine):
    monkeypatch.setenv('DAKT_ASR_ENGINE', engine)
    model = tmp_path / 'am'
    model.mkdir()
    (model / 'final.mdl').write_bytes(b'test-marker')
    (tmp_path / 'model.bin').write_bytes(b'test-marker')
    for name in ['encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt']:
        (tmp_path / name).write_bytes(b'test-marker')
    monkeypatch.setenv('DAKT_ASR_MODEL', str(tmp_path))
    monkeypatch.setattr('pi_microphone.shutil.which', lambda name: '/usr/bin/arecord')
    calls = []
    class Recognizer:
        def __init__(self, model, rate):
            assert rate == 16000
        def AcceptWaveform(self, pcm):
            return False
        def PartialResult(self):
            raise AssertionError('Unstable partial text must not be published')
        def FinalResult(self):
            return json.dumps({'text': 'xin chào'})
    monkeypatch.setitem(sys.modules, 'vosk', SimpleNamespace(Model=lambda path: object(), KaldiRecognizer=Recognizer, SetLogLevel=lambda level: None))
    class Whisper:
        def __init__(self, *args, **kwargs):
            pass
        def transcribe(self, *args, **kwargs):
            return iter([SimpleNamespace(text='xin chào')]), None
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Whisper))
    class Zipformer:
        def create_stream(self):
            return SimpleNamespace(accept_waveform=lambda *args: None,
                                   result=SimpleNamespace(text='xin chào'))
        def decode_stream(self, stream):
            pass
    monkeypatch.setitem(sys.modules, 'sherpa_onnx', SimpleNamespace(OfflineRecognizer=SimpleNamespace(
        from_transducer=lambda **kwargs: Zipformer())))
    monkeypatch.setitem(sys.modules, 'faster_whisper.vad', SimpleNamespace(
        VadOptions=lambda **kwargs: kwargs,
        get_speech_timestamps=lambda *args, **kwargs: [{'start': 0, 'end': 100}]))

    async def scenario():
        reader = asyncio.StreamReader()
        reader.feed_data(b'\0\0' * 1600)
        reader.feed_eof()
        async def wait():
            return 0
        async def create(*args, **kwargs):
            calls.append(args)
            return SimpleNamespace(stdout=reader, returncode=0, wait=wait)
        monkeypatch.setattr('pi_microphone.asyncio.create_subprocess_exec', create)
        mic = PiMicrophone()
        mic.start('mic-request-01')
        mic.start('mic-request-01')
        with pytest.raises(Exception) as exc:
            mic.start('mic-request-02')
        assert exc.value.status_code == 409
        await mic.task
        assert len(calls) == 1 and calls[0][-2:] == ('-d', '12')
        assert 'plughw:CARD=WebCamera,DEV=0' in calls[0]
        assert mic.state['text'] == 'xin chào' and mic.state['status'] == 'done'
        assert mic.state['metrics']['seconds'] == .1
        with pytest.raises(Exception) as exc:
            mic.stop('stale-session')
        assert exc.value.status_code == 409
    asyncio.run(scenario())


def test_whisper_local_vietnamese_and_silence(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_ASR_ENGINE', 'whisper')
    monkeypatch.setenv('DAKT_ASR_MODEL', str(tmp_path))
    (tmp_path / 'model.bin').write_bytes(b'test-marker')
    calls = []
    class Model:
        def __init__(self, path, **options):
            assert path == str(tmp_path)
            assert options == dict(device='cpu', compute_type='int8', cpu_threads=3,
                                   num_workers=1, local_files_only=True)
        def transcribe(self, audio, **options):
            calls.append(options)
            assert audio.dtype.name == 'float32' and max(abs(audio)) <= 1
            return iter([SimpleNamespace(text=' Xin chào. ')] if any(audio) else []), None
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    mic = PiMicrophone()
    mic.model = mic.load_model()
    assert mic.transcribe(b'') == '' and not calls
    assert mic.transcribe(b'\0\0' * 16000) == ''
    assert mic.transcribe(struct.pack('<hh', -32768, 32767)) == 'Xin chào.'
    assert calls[-1]['language'] == 'vi' and calls[-1]['vad_filter'] is True
    assert calls[-1]['beam_size'] == 1
    assert calls[-1]['condition_on_previous_text'] is False


def test_asr_invalid_engine_is_explicit(monkeypatch):
    monkeypatch.setenv('DAKT_ASR_ENGINE', 'unknown')
    with pytest.raises(RuntimeError, match='DAKT_ASR_ENGINE'):
        PiMicrophone().load_model()


def test_auto_stop_requires_speech_then_silence(monkeypatch):
    spans = []
    monkeypatch.setitem(sys.modules, 'faster_whisper.vad', SimpleNamespace(
        VadOptions=lambda **kwargs: kwargs,
        get_speech_timestamps=lambda audio, **kwargs: spans))
    mic = PiMicrophone()
    pcm = b'\0\0' * 32000
    assert not mic.utterance_finished(pcm)
    spans.append({'start': 0, 'end': 31000})
    assert not mic.utterance_finished(pcm)
    spans[0]['end'] = 16000
    assert mic.utterance_finished(pcm)


def test_zipformer_silence_and_model_validation(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_ASR_ENGINE', 'zipformer')
    monkeypatch.setenv('DAKT_ASR_MODEL', str(tmp_path))
    mic = PiMicrophone()
    with pytest.raises(RuntimeError, match='Thiếu model Zipformer'):
        mic.load_model()
    monkeypatch.setitem(sys.modules, 'faster_whisper.vad', SimpleNamespace(
        VadOptions=lambda **kwargs: kwargs,
        get_speech_timestamps=lambda *args, **kwargs: []))
    assert mic.transcribe(b'\0\0' * 16000) == ''


def test_auto_stop_finishes_capture_before_time_limit(monkeypatch):
    monkeypatch.setenv('DAKT_ASR_ENGINE', 'whisper')
    monkeypatch.setattr('pi_microphone.shutil.which', lambda name: '/usr/bin/arecord')
    async def scenario():
        reader = asyncio.StreamReader()
        reader.feed_data(b'\0\0' * 16000)
        reader.feed_eof()
        stopped = []
        async def wait():
            process.returncode = -15
        process = SimpleNamespace(stdout=reader, returncode=None, wait=wait,
                                  terminate=lambda: stopped.append(True))
        async def create(*args, **kwargs):
            return process
        monkeypatch.setattr('pi_microphone.asyncio.create_subprocess_exec', create)
        mic = PiMicrophone()
        mic.model = object()
        def finished(pcm):
            assert mic.state['text'] == ''
            return True
        monkeypatch.setattr(mic, 'utterance_finished', finished)
        monkeypatch.setattr(mic, 'transcribe', lambda pcm: 'Xin chào.')
        mic.start('automatic-stop')
        await mic.task
        assert len(stopped) == 1 and mic.state['status'] == 'done'
        assert mic.state['metrics']['seconds'] == .4
        assert mic.state['text'] == 'Xin chào.' and mic.process is None
    asyncio.run(scenario())


def test_microphone_api_auth_and_audio_interlock(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN', 'test-only-token')
    monkeypatch.setattr('server.ROOT', tmp_path)
    app = create_app(tmp_path / 'mic.sqlite3')
    with TestClient(app) as client:
        body = {'request_id': 'mic-api-request'}
        assert client.post('/api/pi/microphone/start', json=body).status_code == 401
        app.state.pi.speech['status'] = 'PLAYING'
        assert client.post('/api/pi/microphone/start', json=body, headers={'Authorization': 'Bearer test-only-token'}).status_code == 409
        app.state.pi.speech['status'] = 'idle'
        monkeypatch.setattr('pi_microphone.shutil.which', lambda name: None)
        assert client.post('/api/pi/microphone/start', json=body, headers={'Authorization': 'Bearer test-only-token'}).status_code == 503
