"""Verify CIT from the Pi side of the SSH forward, then keep it open."""
import io
import json
from pathlib import Path
import shlex
import subprocess
import time
from urllib.request import Request, urlopen
import wave

BASE = 'http://127.0.0.1:18001'
VOICE = 'Ngọc Huyền'


def get(path, data=None, headers=None):
    with urlopen(Request(BASE + path, data, headers or {}), timeout=20) as response:
        return response.read(12_000_001)


def health():
    status = json.loads(get('/health'))
    if status.get('status') != 'ok' or status.get('device') != 'cuda' or status.get('sample_rate') != 48000:
        raise ValueError('CIT GPU /health is not ready on Pi')


def verify():
    health()
    voices = json.loads(get('/voices'))
    if not any(item.get('id') == VOICE for item in voices):
        raise ValueError('Ngoc Huyen is missing from /voices on Pi')
    project = subprocess.check_output(
        ['systemctl', '--user', 'show', 'signassist-connected.service', '-p', 'WorkingDirectory', '--value'],
        text=True, timeout=5).strip()
    env = Path(project) / 'backend/.env.local'
    headers = {'Content-Type': 'application/json'}
    if project and env.is_file():
        for line in env.read_text().splitlines():
            key, _, raw = line.partition('=')
            if key.strip() == 'DAKT_CIT_API_KEY' and (value := shlex.split(raw, comments=True)):
                headers['X-API-Key'] = value[0]
                break
    body = json.dumps({'text': 'Xin chào.', 'voice_id': VOICE, 'format': 'wav', 'speed': 1}).encode()
    audio = get('/api/tts/generate', body, headers)
    if len(audio) > 12_000_000:
        raise ValueError('CIT WAV exceeds size limit')
    with wave.open(io.BytesIO(audio)) as wav:
        frames = wav.getnframes()
        if ((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (48000, 1, 2)
                or not frames or len(wav.readframes(frames)) != frames * 2):
            raise ValueError('CIT returned an invalid or incomplete WAV')
    print(f'PASS - Pi -> CIT: /health CUDA, /voices Ngoc Huyen, WAV {frames} frames at 48000 Hz.', flush=True)


if __name__ == '__main__':
    try:
        verify()
        while True:
            time.sleep(15)
            health()
    except (OSError, ValueError, subprocess.SubprocessError, wave.Error, EOFError) as issue:
        print(f'BLOCKED - CIT tunnel from Pi: {type(issue).__name__}. Check CIT, Wi-Fi and port 18001.', flush=True)
        raise SystemExit(1)
