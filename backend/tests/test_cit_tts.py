from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import URLError
import wave

import pytest

import pi_tts


def test_cit_converts_verified_wav_and_handles_network_failure(monkeypatch):
    monkeypatch.setenv('DAKT_CIT_ENABLED', '1')
    monkeypatch.setenv('DAKT_CIT_API_KEY', 'test-key')
    raw = b'\x00\x01' * 480

    def open_cit(request, timeout):
        assert request.full_url == 'http://127.0.0.1:18001/api/tts/generate'
        assert request.get_header('X-api-key') == 'test-key'
        assert json.loads(request.data) == {
            'voice_id': 'Ngọc Huyền', 'text': 'Xin chào', 'format': 'wav', 'speed': 0.85,
        }
        return BytesIO(pi_tts.pcm_wav(raw, 48000))

    monkeypatch.setattr(pi_tts, 'urlopen', open_cit)
    monkeypatch.setattr(pi_tts.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(stdout=raw[:480]))
    tts = pi_tts.PiTTS()
    with wave.open(BytesIO(tts.synthesize_cit('Xin chào', 85))) as audio:
        assert (audio.getframerate(), audio.getsampwidth(), audio.getnchannels()) == (24000, 2, 1)

    def offline(*_args, **_kwargs):
        raise URLError('tunnel down')

    monkeypatch.setattr(pi_tts, 'urlopen', offline)
    with pytest.raises(RuntimeError, match='Mất kết nối CIT'):
        tts.synthesize_cit('Xin chào', 85)
