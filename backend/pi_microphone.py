"""Bounded Pi USB recording; publish completed Vietnamese utterances only."""
import asyncio
from collections import deque
import json
import math
import os
import shutil
from pathlib import Path
import struct
from time import monotonic

from fastapi import HTTPException


def pcm_stats(pcm):
    if not pcm or len(pcm) % 2:
        return None
    samples = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
    return {'seconds': round(len(samples) / 16000, 2),
            'rms': round(math.sqrt(sum(x * x for x in samples) / len(samples))),
            'peak': max(abs(x) for x in samples),
            'dc_offset': round(sum(samples) / len(samples), 1),
            'clipped_percent': round(sum(abs(x) >= 32767 for x in samples) * 100 / len(samples), 3)}


class PiMicrophone:
    def __init__(self):
        self.state = {'status': 'idle', 'text': '', 'error': '', 'session': None,
                      'source': 'WebCamera · USB', 'metrics': None}
        self.version = 0
        self.task = None
        self.process = None
        self.stop_requested = False
        self.ids = deque(maxlen=64)
        self.model = None
        self.engine = os.getenv('DAKT_ASR_ENGINE', 'vosk').lower()
        self.state['engine'] = self.engine

    def load_model(self):
        path = Path(os.getenv('DAKT_ASR_MODEL', str(Path(__file__).parent / 'models/vosk-model-small-vn-0.4')))
        if self.engine == 'zipformer':
            files = {key: str(path / name) for key, name in {
                'encoder': 'encoder.int8.onnx', 'decoder': 'decoder.onnx',
                'joiner': 'joiner.int8.onnx', 'tokens': 'tokens.txt'}.items()}
            if not all(Path(name).is_file() for name in files.values()):
                raise RuntimeError('Thiếu model Zipformer tiếng Việt. Kiểm tra DAKT_ASR_MODEL.')
            from sherpa_onnx import OfflineRecognizer
            return OfflineRecognizer.from_transducer(
                **files, num_threads=2, sample_rate=16000, feature_dim=80,
                decoding_method='modified_beam_search', max_active_paths=4, provider='cpu')
        if self.engine == 'whisper':
            if not (path / 'model.bin').is_file():
                raise RuntimeError('Chưa có model Whisper local. Kiểm tra DAKT_ASR_MODEL.')
            from faster_whisper import WhisperModel
            return WhisperModel(str(path), device='cpu', compute_type='int8',
                                cpu_threads=3, num_workers=1, local_files_only=True)
        if self.engine != 'vosk':
            raise RuntimeError('DAKT_ASR_ENGINE chỉ hỗ trợ zipformer, whisper hoặc vosk.')
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        if not (path / 'am/final.mdl').is_file():
            raise RuntimeError('Chưa cấu hình model Vosk tiếng Việt trên Pi. Kiểm tra DAKT_ASR_MODEL.')
        return Model(str(path))

    def transcribe(self, pcm):
        import numpy as np
        audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        if not len(audio):
            return ''
        if self.engine == 'zipformer':
            from faster_whisper.vad import VadOptions, get_speech_timestamps
            if not get_speech_timestamps(audio, vad_options=VadOptions()):
                return ''
            stream = self.model.create_stream()
            stream.accept_waveform(16000, audio)
            self.model.decode_stream(stream)
            return stream.result.text.strip()[:2000]
        segments, _ = self.model.transcribe(
            audio, language='vi', task='transcribe', beam_size=1, temperature=0.0,
            condition_on_previous_text=False, vad_filter=True,
            vad_parameters={'min_silence_duration_ms': 500, 'speech_pad_ms': 200})
        return ' '.join(segment.text.strip() for segment in segments).strip()[:2000]

    def utterance_finished(self, pcm):
        import numpy as np
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        spans = get_speech_timestamps(audio, vad_options=VadOptions(
            min_silence_duration_ms=650, min_speech_duration_ms=150, speech_pad_ms=0))
        return bool(spans and len(audio) - spans[-1]['end'] >= 16000 * .8)

    @property
    def busy(self):
        return bool(self.task and not self.task.done())

    def start(self, request_id):
        if request_id in self.ids:
            return
        if self.busy:
            raise HTTPException(409, 'Micro Pi đang được sử dụng. Chờ hoặc dừng phiên hiện tại.')
        if not shutil.which('arecord'):
            raise HTTPException(503, 'Pi chưa có arecord hoặc chưa hỗ trợ micro USB.')
        self.ids.append(request_id)
        self.stop_requested = False
        self.state.update(status='connecting', text='', error='', session=request_id, metrics=None)
        self.version += 1
        self.task = asyncio.create_task(self.run())

    def stop(self, session):
        if session != self.state['session']:
            raise HTTPException(409, 'Phiên micro đã thay đổi. Hãy cập nhật rồi thử lại.')
        self.stop_requested = True
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass

    async def run(self):
        pcm = bytearray()
        texts = []
        checked_bytes = 0
        try:
            if self.model is None:
                self.model = await asyncio.to_thread(self.load_model)
            if self.stop_requested:
                self.state.update(status='cancelled')
                return
            recognizer = None
            if self.engine == 'vosk':
                from vosk import KaldiRecognizer
                recognizer = await asyncio.to_thread(KaldiRecognizer, self.model, 16000)
            self.process = await asyncio.create_subprocess_exec(
                'arecord', '-q', '-D', os.getenv('DAKT_MIC_DEVICE', 'plughw:CARD=WebCamera,DEV=0'),
                '-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw', '-d', '12',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self.state.update(status='recording')
            self.version += 1
            if self.stop_requested:
                self.process.terminate()
            while True:
                chunk = await asyncio.wait_for(self.process.stdout.read(3200), 3)
                if not chunk:
                    break
                pcm.extend(chunk)
                if len(pcm) > 16000 * 2 * 13:
                    raise RuntimeError('Bản thu vượt giới hạn thời gian.')
                if self.engine in ('whisper', 'zipformer') and not self.stop_requested and len(pcm) - checked_bytes >= 12800:
                    checked_bytes = len(pcm)
                    if await asyncio.to_thread(self.utterance_finished, bytes(pcm)):
                        self.stop_requested = True
                        try:
                            self.process.terminate()
                        except ProcessLookupError:
                            pass
                        break
                if recognizer and await asyncio.to_thread(recognizer.AcceptWaveform, chunk):
                    data = json.loads(recognizer.Result())
                    if data.get('text'):
                        texts.append(data['text'])
            await self.process.wait()
            if self.process.returncode and not self.stop_requested:
                raise RuntimeError('Không thu được micro WebCamera. Kiểm tra dây USB và thiết bị ALSA.')
            self.state.update(status='processing', metrics=pcm_stats(pcm))
            self.version += 1
            started = monotonic()
            if recognizer:
                data = json.loads(await asyncio.to_thread(recognizer.FinalResult))
                if data.get('text'):
                    texts.append(data['text'])
                text = ' '.join(texts)[:2000]
            else:
                text = await asyncio.to_thread(self.transcribe, bytes(pcm))
            metrics = pcm_stats(pcm)
            if metrics:
                metrics['decode_seconds'] = round(monotonic() - started, 2)
            self.state.update(status='done', text=text, metrics=metrics)
            if not self.state['text']:
                self.state['error'] = 'Chưa nhận được lời nói. Thử nói gần micro camera hơn.'
        except asyncio.CancelledError:
            self.state.update(status='cancelled')
        except Exception as issue:
            self.state.update(status='error', error=str(issue) if isinstance(issue, RuntimeError)
                              else 'Không nhận dạng được tiếng nói trên Pi. Kiểm tra bộ ASR và micro USB.')
        finally:
            if self.process and self.process.returncode is None:
                try:
                    self.process.terminate()
                    await asyncio.wait_for(self.process.wait(), 2)
                except ProcessLookupError:
                    pass
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            self.process = None
            self.version += 1

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
