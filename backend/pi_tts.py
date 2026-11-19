"""Vietnamese speech synthesis and PCM processing on the Pi."""
from array import array
import base64
from io import BytesIO
import json
import logging
import math
import os
import shutil
import struct
import subprocess
import sys
from time import monotonic
import wave
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


VOICE_NAMES = {
    'Aoede': 'Aoede · Gemini · Nữ, nhẹ nhàng',
    'Kore': 'Kore · Gemini · Nữ, rõ ràng',
}
CIT_VOICE = 'cit-ngoc-huyen'


def adjust_wav(audio, volume, gain_db, muted):
    with wave.open(BytesIO(audio), 'rb') as source:
        params = source.getparams()
        samples = array('h')
        samples.frombytes(source.readframes(params.nframes))
    if sys.byteorder == 'big':
        samples.byteswap()
    level = 0 if muted else volume / 100 * 10 ** (gain_db / 20)
    peak = max(map(abs, samples), default=0)
    if peak:
        level = min(level, 32760 / peak)
    ramp = max(1, round(params.framerate * .015))
    for index, sample in enumerate(samples):
        envelope = min(1, index / ramp, (len(samples) - 1 - index) / ramp)
        samples[index] = round(sample * level * envelope)
    if sys.byteorder == 'big':
        samples.byteswap()
    output = BytesIO()
    with wave.open(output, 'wb') as target:
        target.setparams(params)
        target.writeframes(samples.tobytes())
    return output.getvalue()


class PiTTS:
    def __init__(self):
        self.offline_executable = shutil.which('espeak-ng')
        self.quota_until = 0

    def offline(self, text, speed):
        if not self.offline_executable:
            raise RuntimeError('Pi chưa có eSpeak NG để đọc ngoại tuyến.')
        try:
            result = subprocess.run(
                [self.offline_executable, '-v', 'vi+f3', '-s', str(round(155 * speed / 100)),
                 '-a', '80', '--stdout', '--stdin'],
                input=text.encode(), capture_output=True, check=True, timeout=12,
            )
            with wave.open(BytesIO(result.stdout), 'rb') as source:
                frames = source.readframes(source.getnframes())
                if source.getnchannels() != 1 or source.getsampwidth() != 2 or not frames:
                    raise ValueError('invalid offline PCM')
                return pcm_wav(frames, source.getframerate())
        except (OSError, subprocess.SubprocessError, ValueError, EOFError, wave.Error):
            raise RuntimeError('eSpeak NG không tạo được giọng ngoại tuyến.') from None

    def gemini_key(self):
        return os.getenv('DAKT_GEMINI_TTS_KEY') or (
            os.getenv('GEMINI_API_KEY') if os.getenv('DAKT_GEMINI_TTS_USE_CHAT_KEY') == '1' else None
        )

    def voices(self):
        voices = [{'id': voice, 'label': label, 'available': bool(self.gemini_key())}
                  for voice, label in VOICE_NAMES.items()]
        if os.getenv('DAKT_CIT_ENABLED') == '1':
            voices.append({'id': CIT_VOICE, 'label': 'CIT Voice Studio – Ngọc Huyền', 'available': True})
        return voices

    def synthesize_cit(self, text, speed):
        if os.getenv('DAKT_CIT_ENABLED') != '1':
            raise RuntimeError('CIT Voice Studio chưa được cấu hình.')
        started = monotonic()
        headers = {'Content-Type': 'application/json'}
        if key := os.getenv('DAKT_CIT_API_KEY'):
            headers['X-API-Key'] = key
        body = json.dumps({'text': text, 'voice_id': 'Ngọc Huyền', 'format': 'wav', 'speed': speed / 100}).encode()
        request = Request('http://127.0.0.1:18001/api/tts/generate', body, headers)
        try:
            with urlopen(request, timeout=15) as response:
                first = response.read(44)
                first_at = monotonic()
                audio = first + response.read(12_000_001)
            received = monotonic()
            if len(audio) > 12_000_000:
                raise ValueError('oversize WAV')
            with wave.open(BytesIO(audio), 'rb') as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 48000):
                    raise ValueError('unexpected CIT WAV')
                size = source.getnframes() * 2
                if not size or len(source.readframes(source.getnframes())) != size:
                    raise ValueError('incomplete CIT WAV')
            converted = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', 'pipe:0',
                                        '-ar', '24000', '-ac', '1', '-f', 's16le', 'pipe:1'],
                                       input=audio, capture_output=True, check=True, timeout=8).stdout
            if not converted or len(converted) % 2 or len(converted) > 4_800_000:
                raise ValueError('invalid converted PCM')
            logging.getLogger('uvicorn.error').info('CIT timing: first_ms=%.0f transfer_ms=%.0f convert_ms=%.0f',
                                                    (first_at - started) * 1000, (received - first_at) * 1000,
                                                    (monotonic() - received) * 1000)
            return pcm_wav(converted, 24000)
        except HTTPError as issue:
            raise RuntimeError(f'CIT Voice Studio từ chối yêu cầu (HTTP {issue.code}).') from None
        except (URLError, TimeoutError):
            raise RuntimeError('Mất kết nối CIT Voice Studio. Kiểm tra laptop, hotspot và đường hầm SSH.') from None
        except (OSError, EOFError, ValueError, wave.Error, subprocess.SubprocessError):
            raise RuntimeError('CIT Voice Studio trả âm thanh không hợp lệ hoặc Pi thiếu bộ chuyển đổi WAV.') from None

    def synthesize_cloud(self, text, voice, speed):
        key = self.gemini_key()
        if not key or voice not in ('Aoede', 'Kore'):
            raise RuntimeError('Giọng đã chọn chưa được cấu hình trên Pi.')
        if monotonic() < self.quota_until:
            raise RuntimeError('Gemini TTS đang hết hạn mức hoặc bị giới hạn lượt gọi.')
        try:
            body = {
                'contents': [{'parts': [{'text': f'Đọc nguyên văn đoạn sau bằng tiếng Việt, ngắt theo dấu câu, tốc độ khoảng {speed / 100:.2f} lần bình thường.\n\n{text}'}]}],
                'generationConfig': {'responseModalities': ['AUDIO'], 'speechConfig': {
                    'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}}},
            }
            request = Request('https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent',
                              json.dumps(body).encode(), {'Content-Type': 'application/json', 'x-goog-api-key': key})
            with urlopen(request, timeout=25) as response:
                reply = json.loads(response.read(6_500_000))
            inline = next(part['inlineData'] for part in reply['candidates'][0]['content']['parts'] if 'inlineData' in part)
            mime = inline['mimeType'].lower().replace(' ', '')
            if not mime.startswith('audio/l16;') or 'rate=24000' not in mime.split(';'):
                raise ValueError('unexpected PCM format')
            pcm = base64.b64decode(inline['data'], validate=True)
            if not pcm or len(pcm) % 2 or len(pcm) > 4_800_000:
                raise ValueError('invalid PCM length')
            return pcm_wav(pcm, 24000)
        except HTTPError as issue:
            if issue.code == 429:
                delay = 30
                try:
                    for detail in json.loads(issue.read(65536)).get('error', {}).get('details', []):
                        if 'retryDelay' in detail:
                            delay = max(delay, min(86400, float(detail['retryDelay'].removesuffix('s'))))
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
                self.quota_until = monotonic() + delay
                raise RuntimeError('Gemini TTS đang hết hạn mức hoặc bị giới hạn lượt gọi.') from None
            raise RuntimeError(f'Gemini TTS từ chối yêu cầu (HTTP {issue.code}).') from None
        except (TimeoutError, URLError) as issue:
            if isinstance(issue, TimeoutError) or isinstance(getattr(issue, 'reason', None), TimeoutError):
                raise RuntimeError('Gemini TTS quá thời gian chờ.') from None
            raise RuntimeError('Pi không kết nối được Gemini TTS.') from None
        except (OSError, ValueError, KeyError, IndexError, StopIteration, TypeError):
            raise RuntimeError(f'{VOICE_NAMES[voice]} không tạo được âm thanh. Kiểm tra cấu hình, mạng hoặc hạn mức.') from None

    def status(self):
        configured = bool(self.gemini_key())
        limited = monotonic() < self.quota_until
        return {'engine': 'Gemini TTS', 'ready': configured and not limited, 'benchmark': None,
                'offline_available': bool(self.offline_executable), 'quota_limited': limited,
                'message': 'Gemini TTS đang bị giới hạn lượt gọi.' if limited else
                           'Gemini TTS đã có cấu hình.' if configured else 'Gemini TTS chưa được cấu hình trên Pi.'}


def pcm_wav(pcm, rate):
    output = BytesIO()
    with wave.open(output, 'wb') as target:
        target.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        target.writeframes(pcm)
    return output.getvalue()


def speaker_test_wav():
    rate = 24000
    pcm = b''.join(struct.pack('<h', round(6500 * math.sin(2 * math.pi * 660 * index / rate)))
                   for index in range(rate // 2))
    return pcm_wav(pcm, rate)
