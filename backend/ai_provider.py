"""Text-only provider boundary; no tools, MQTT, credentials or SDK in the frontend."""
import asyncio
import json
import os
import logging
from time import sleep
from random import uniform
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIError(Exception):
    def __init__(self, message, *, retryable=False, status_code=None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class MockProvider:
    name = 'mock'

    async def answer(self, question):
        return 'BẢN THỬ MOCK · Chưa gửi đến AI. Câu hỏi của bạn: ' + question


class GeminiProvider:
    name = 'gemini'

    def __init__(self, key, model='gemini-3.1-flash-lite'):
        self.key = key
        self.model = model

    async def answer(self, question):
        return await asyncio.to_thread(self._answer, question)

    def _answer(self, question):
        body = {'systemInstruction': {'parts': [{'text':
            'Bạn là Deafy, trợ lý hỗ trợ giao tiếp bằng ngôn ngữ ký hiệu. Trả lời tiếng Việt tự nhiên trong 1–3 câu ngắn, trừ khi được yêu cầu giải thích chi tiết. Không lặp câu hỏi, không thêm lời mở đầu hoặc thông tin hệ thống. '
            'Bạn chỉ trả lời văn bản; không điều khiển thiết bị.'}]},
            'contents': [{'role': 'user', 'parts': [{'text': question}]}],
            'generationConfig': {'maxOutputTokens': 512}}
        request = Request('https://generativelanguage.googleapis.com/v1beta/models/'
                          + self.model + ':generateContent',
                          data=json.dumps(body).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'x-goog-api-key': self.key})
        try:
            for attempt in range(2):
                try:
                    with urlopen(request, timeout=10) as response:
                        data = json.load(response)
                    break
                except HTTPError as issue:
                    if not 500 <= issue.code <= 599 or attempt == 1:
                        raise
                    sleep(2**attempt + uniform(0, .2))
                except (URLError, TimeoutError, OSError):
                    if attempt == 1:
                        raise
                    sleep(1 + uniform(0, .2))
        except HTTPError as exc:
            # Provider bodies/URLs can contain secrets; never relay them to clients or logs.
            messages = {429: 'Gemini đã hết hạn mức Free Tier. Chờ rồi gửi lại; câu gốc vẫn được giữ.',
                        400: 'Gemini từ chối yêu cầu. Kiểm tra model và cấu hình backend.',
                        401: 'Gemini API key không hợp lệ. Kiểm tra key tại backend.',
                        403: 'Gemini chưa được cấp quyền. Kiểm tra key và Free Tier tại AI Studio.',
                        404: 'Model Gemini không còn khả dụng. Kiểm tra model có Free Tier.',
                        503: 'Gemini tạm thời quá tải. Thử lại sau; camera và câu gốc vẫn được giữ.'}
            message = messages.get(exc.code, 'Dịch vụ Gemini đang lỗi. Hãy thử lại sau.')
            raise AIError(f'{message} [HTTP {exc.code}]', retryable=exc.code == 429 or 500 <= exc.code <= 599,
                          status_code=exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise AIError('Không kết nối được Gemini. Kiểm tra Internet; camera và câu gốc vẫn được giữ.', retryable=True) from None
        except (ValueError, TypeError):
            raise AIError('Gemini trả dữ liệu không hợp lệ. Hãy gửi lại.') from None
        candidates = data.get('candidates', []) if isinstance(data, dict) else []
        if not candidates or candidates[0].get('finishReason') not in ('STOP', 'MAX_TOKENS'):
            raise AIError('Gemini chưa thể trả lời câu hỏi này. Hãy chỉnh sửa và gửi lại.')
        parts = candidates[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
        if not text:
            raise AIError('Gemini không trả lời bằng văn bản. Hãy gửi lại.')
        return text[:4000]


class GroqProvider:
    name = 'groq'

    def __init__(self, key, model='openai/gpt-oss-20b'):
        self.key, self.model = key, model

    async def answer(self, question):
        return await asyncio.to_thread(self._answer, question)

    def _answer(self, question):
        body = {'model': self.model, 'messages': [
            {'role': 'system', 'content': 'Bạn là Deafy, trợ lý hỗ trợ giao tiếp bằng ngôn ngữ ký hiệu. Trả lời tiếng Việt tự nhiên trong 1–3 câu ngắn, trừ khi được yêu cầu giải thích chi tiết. Không lặp câu hỏi, không thêm lời mở đầu hoặc thông tin hệ thống. '
             'Chỉ trả lời văn bản; không điều khiển thiết bị, không bịa địa điểm hoặc dữ liệu bản đồ.'},
            {'role': 'user', 'content': question}], 'max_completion_tokens': 768, 'stream': False}
        if self.model.startswith('openai/gpt-oss-'):
            body.update(include_reasoning=False, reasoning_effort='low')
        request = Request('https://api.groq.com/openai/v1/chat/completions', method='POST',
                          data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key,
                                   'User-Agent': 'SignAssist/1.0 (Raspberry Pi backend)'})
        try:
            with urlopen(request, timeout=10) as response:
                data = json.load(response)
            choice = data['choices'][0]
            text = choice['message']['content']
            if choice.get('finish_reason') not in ('stop', 'length') or not isinstance(text, str) or not text.strip():
                raise AIError('Groq chưa trả lời bằng văn bản. Câu gốc vẫn được giữ.')
            return text.strip()[:4000]
        except HTTPError as issue:
            messages = {401: 'Groq API key không hợp lệ. Kiểm tra cấu hình riêng trên Pi.',
                        403: 'Groq chưa được cấp quyền cho yêu cầu/model này.',
                        400: 'Groq từ chối cấu hình model hoặc yêu cầu.',
                        404: 'Model Groq chưa khả dụng với tài khoản này.',
                        429: 'Groq đã hết hạn mức. Chờ rồi thử lại.'}
            raise AIError(messages.get(issue.code, 'Groq tạm thời không phục vụ được yêu cầu.') + f' [HTTP {issue.code}]',
                          retryable=issue.code == 429 or 500 <= issue.code <= 599, status_code=issue.code) from None
        except (URLError, TimeoutError, OSError):
            raise AIError('Không kết nối được Groq. Câu gốc vẫn được giữ.', retryable=True) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise AIError('Groq trả dữ liệu không hợp lệ. Câu gốc vẫn được giữ.') from None


class FallbackProvider:
    name = 'gemini'

    def __init__(self, primary, backup=None):
        self.primary, self.backup = primary, backup
        self.active_provider, self.stage = 'gemini', 'idle'

    def status(self):
        return {'active': self.active_provider, 'stage': self.stage, 'fallback_configured': self.backup is not None}

    async def answer(self, question):
        self.active_provider, self.stage = 'gemini', 'processing'
        try:
            text = await self.primary.answer(question)
            self.stage = 'done'
            return text
        except (AIError, TimeoutError) as issue:
            transient = isinstance(issue, TimeoutError) or issue.retryable
            if not transient:
                self.stage = 'error'
                raise
            if not self.backup:
                self.active_provider, self.stage = 'offline', 'offline'
                if isinstance(issue, AIError):
                    raise
                raise AIError('Gemini quá thời gian chờ; Groq chưa được cấu hình. Câu gốc vẫn được giữ.') from None
        logging.getLogger(__name__).warning('AI fallback: Gemini unavailable; using Groq (sequential)')
        self.active_provider, self.stage = 'groq', 'processing'
        try:
            text = await self.backup.answer(question)
            self.stage = 'done'
            return text
        except (AIError, TimeoutError) as issue:
            if isinstance(issue, AIError) and issue.status_code in (400, 401, 403, 404):
                self.stage = 'error'
                raise
            self.active_provider, self.stage = 'offline', 'offline'
            raise AIError('Gemini và Groq hiện chưa dùng được. Giữ câu gốc để chỉnh sửa hoặc phát loa.') from None


def create_provider():
    # Enabling Gemini is explicit even if a key happens to exist on this machine.
    choice = os.getenv('DAKT_AI_PROVIDER', 'mock')
    if choice == 'mock':
        return MockProvider()
    if choice != 'gemini':
        raise AIError('DAKT_AI_PROVIDER phải là mock hoặc gemini.')
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        return MockProvider()
    model = os.getenv('GEMINI_MODEL', 'gemini-3.1-flash-lite')
    # Keep a fixed verified Free Tier model; never silently fall back to a paid model.
    if model != 'gemini-3.1-flash-lite':
        raise AIError('Bản thử chỉ cho phép gemini-3.1-flash-lite. Xác minh Free Tier trước khi đổi model.')
    groq_key = os.getenv('GROQ_API_KEY', '').strip()
    groq_model = os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b').strip()
    if groq_key and (not groq_model or len(groq_model) > 120):
        raise AIError('GROQ_MODEL không hợp lệ. Kiểm tra cấu hình riêng backend.')
    return FallbackProvider(GeminiProvider(key, model), GroqProvider(groq_key, groq_model) if groq_key else None)
