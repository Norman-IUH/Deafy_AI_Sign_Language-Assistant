from test_pi_modes import sample_wav
import asyncio
from io import BytesIO
import json
from urllib.error import HTTPError

import pytest
from ai_provider import AIError, GeminiProvider, GroqProvider, FallbackProvider, create_provider
from server import create_app


def run(coro):
    return asyncio.run(coro)


class Stub:
    def __init__(self, result, events, name):
        self.result, self.events, self.name = result, events, name
    async def answer(self, question):
        self.events.append(self.name)
        if isinstance(self.result, Exception):raise self.result
        return self.result


def test_primary_success_never_calls_backup():
    events=[];provider=FallbackProvider(Stub('Gemini text',events,'gemini'),Stub('Groq text',events,'groq'))
    assert run(provider.answer('private question'))=='Gemini text'
    assert events==['gemini'] and provider.status()['active']=='gemini'


@pytest.mark.parametrize('failure',[AIError('503',retryable=True,status_code=503),AIError('429',retryable=True,status_code=429),TimeoutError()])
def test_transient_primary_failure_calls_backup_sequentially(failure):
    events=[];provider=FallbackProvider(Stub(failure,events,'gemini'),Stub('Groq text',events,'groq'))
    assert run(provider.answer('private question'))=='Groq text'
    assert events==['gemini','groq'] and provider.status()=={'active':'groq','stage':'done','fallback_configured':True}


@pytest.mark.parametrize('code',[400,401,403,404])
def test_auth_and_config_failure_does_not_call_backup(code):
    events=[];provider=FallbackProvider(Stub(AIError('Config error',status_code=code),events,'gemini'),Stub('not called',events,'groq'))
    with pytest.raises(AIError,match='Config'):run(provider.answer('private question'))
    assert events==['gemini'] and provider.stage=='error'


@pytest.mark.parametrize('code',[401,403,429,500,503,504])
def test_primary_retry_classification_and_redaction(monkeypatch,code):
    calls=[];sleeps=[]
    def fail(request,timeout):
        calls.append(timeout);raise HTTPError('https://secret?key=PRIVATE',code,'PRIVATE',{},None)
    monkeypatch.setattr('ai_provider.urlopen',fail);monkeypatch.setattr('ai_provider.sleep',sleeps.append)
    with pytest.raises(AIError) as error:GeminiProvider('PRIVATE')._answer('private question')
    assert error.value.retryable==(code==429 or code>=500) and error.value.status_code==code and 'PRIVATE' not in str(error.value)
    assert len(calls)==(2 if code>=500 else 1) and all(timeout==10 for timeout in calls)
    assert len(sleeps)==(1 if code>=500 else 0)


def test_groq_request_is_text_only_and_ignores_reasoning(monkeypatch):
    def response(request,timeout):
        assert request.full_url=='https://api.groq.com/openai/v1/chat/completions'
        assert request.get_header('Authorization')=='Bearer PRIVATE' and timeout==10
        assert request.get_header('User-agent')=='SignAssist/1.0 (Raspberry Pi backend)'
        body=json.loads(request.data)
        assert body['model']=='openai/gpt-oss-20b' and body['include_reasoning'] is False
        assert body['reasoning_effort']=='low' and body['stream'] is False
        assert 'tools' not in body and 'reasoning_format' not in body
        return BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'Xin chào.','reasoning':'INTERNAL'}}]}).encode())
    monkeypatch.setattr('ai_provider.urlopen',response)
    assert run(GroqProvider('PRIVATE').answer('Chào'))=='Xin chào.'


@pytest.mark.parametrize('code',[401,403,429,503])
def test_groq_failure_is_redacted_and_not_retried(monkeypatch,code):
    calls=[]
    def fail(*args,**kwargs):calls.append(1);raise HTTPError('PRIVATE',code,'PRIVATE',{},None)
    monkeypatch.setattr('ai_provider.urlopen',fail)
    with pytest.raises(AIError) as error:run(GroqProvider('PRIVATE').answer('Chào'))
    assert len(calls)==1 and 'PRIVATE' not in str(error.value)


def test_both_fail_keep_draft_and_explicit_offline_speech_still_works(tmp_path,monkeypatch,caplog):
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'fallback.sqlite3').state.pi;events=[]
    pi.provider=FallbackProvider(Stub(AIError('PRIVATE',retryable=True),events,'gemini'),Stub(AIError('PRIVATE',retryable=True),events,'groq'))
    pi.write_buffer('ai','Câu gốc')
    async def scenario():
        pi.ask(dict(request_id='fallback-both-fail',epoch=pi.epoch,text='Câu gốc'))
        await pi.task
        assert pi.ai['status']=='error' and pi.ai['provider']=='offline' and pi.buffers['ai']['text']=='Câu gốc'
        assert not pi.pending and 'PRIVATE' not in json.dumps(pi.snapshot())
        class MQTT:
            connected=True;error=''
            def publish(self,kind,packet):assert kind in ('mode','speech')
        pi.mqtt=MQTT();pi.tts.ready=True
        monkeypatch.setattr(pi.tts,'synthesize_cloud',lambda text, voice, speed:sample_wav())
        monkeypatch.setenv('DAKT_AUDIO_BASE_URL','http://192.168.1.164:8001')
        pi.speak(dict(request_id='fallback-original-speech',epoch=pi.epoch,text='Câu gốc'));await pi.task
        assert pi.pending['speech']['packet']['mode']=='ai' and pi.audio['wav']!=sample_wav()
    run(scenario());assert 'PRIVATE' not in caplog.text


def test_fallback_success_rewrite_still_requires_confirmation(tmp_path,monkeypatch):
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'rewrite.sqlite3').state.pi;events=[]
    pi.provider=FallbackProvider(Stub(TimeoutError(),events,'gemini'),Stub('Xin chào.',events,'groq'))
    pi.write_buffer('ai','xin chào')
    async def scenario():
        pi.ask(dict(request_id='rewrite-fallback',epoch=pi.epoch,text='xin chào',task='rewrite'));await pi.task
    run(scenario())
    assert pi.ai['provider']=='groq' and pi.ai['proposal']=='Xin chào.'
    assert pi.buffers['ai']['text']=='xin chào' and not pi.pending


def test_factory_and_public_status_do_not_expose_credentials(monkeypatch):
    monkeypatch.setenv('DAKT_AI_PROVIDER','gemini');monkeypatch.setenv('GEMINI_API_KEY','PRIMARY-PRIVATE')
    monkeypatch.setenv('GROQ_API_KEY','BACKUP-PRIVATE');monkeypatch.setenv('GROQ_MODEL','openai/gpt-oss-20b')
    provider=create_provider();assert isinstance(provider,FallbackProvider) and provider.backup.model=='openai/gpt-oss-20b'
    assert 'PRIVATE' not in json.dumps(provider.status())


def test_missing_backup_reports_primary_failure_without_extra_calls():
    events=[];provider=FallbackProvider(Stub(AIError('Primary unavailable',retryable=True),events,'gemini'))
    with pytest.raises(AIError,match='Primary'):run(provider.answer('Chào'))
    assert events==['gemini'] and provider.active_provider=='offline' and not provider.status()['fallback_configured']
