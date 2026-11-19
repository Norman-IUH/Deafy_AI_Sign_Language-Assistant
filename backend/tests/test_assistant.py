import asyncio
from io import BytesIO
import json
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient
from ai_provider import AIError, GeminiProvider
from assistant import checked_rewrite, place_query, _search
from recognition_ranking import ranked_labels
from server import create_app


def test_rewrite_guard_preserves_negation_numbers_and_does_not_invent_meaning():
    assert checked_rewrite('tôi không muốn uống nước', 'Tôi không muốn uống nước.') == 'Tôi không muốn uống nước.'
    for proposal in ['Tôi muốn uống nước.', 'Tôi không muốn uống nước lúc 5 giờ.', 'Uống nước tôi không muốn.']:
        with pytest.raises(AIError): checked_rewrite('tôi không muốn uống nước', proposal)


def test_rewrite_explicit_accept_and_no_auto_speech(tmp_path,monkeypatch):
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'assistant.sqlite3').state.pi
    class Provider:
        async def answer(self,text):return 'Tôi muốn uống nước.'
    pi.provider=Provider();pi.write_buffer('ai','tôi muốn uống nước')
    async def scenario():
        pi.ask(dict(epoch=pi.epoch,request_id='rewrite-once',text='tôi muốn uống nước',task='rewrite'))
        await pi.task
    asyncio.run(scenario())
    assert pi.ai['proposal']=='Tôi muốn uống nước.' and pi.buffers['ai']['text']=='tôi muốn uống nước'
    assert not pi.pending and pi.speech['status']=='idle'
    pi.edit(dict(epoch=pi.epoch,request_id='accept-proposal',mode='ai',text=pi.ai['proposal'],expected_revision=1))
    assert pi.buffers['ai']['text']=='Tôi muốn uống nước.' and not pi.pending


def test_ranked_probabilities_and_real_labels_only():
    labels={'Xin_Chao':0,'An_Com':1,'Tim':2,'Me':3}
    result=ranked_labels([.1,.6,.25,.05],labels)
    assert [x['label'] for x in result]==['an_com','tim','xin_chao']
    assert result[0]['confidence']==.6
    for probabilities in ([float('nan'),.6,.25,.05],[0,0,0,0],[-1,1,1,0]):
        with pytest.raises(ValueError):ranked_labels(probabilities,labels)


def test_confirmed_and_uncertain_selection_replace_delete_and_log(tmp_path,monkeypatch):
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'correction.sqlite3').state.pi
    event=dict(id='event-low',label='an_com',text='Ăn cơm',confirmed=False,confidence=.5,
               candidates=ranked_labels([.5,.3,.2],{'An_Com':0,'Xin_Chao':1,'Tim':2}))
    pi.sign(event);pi.sign(event)
    assert pi.suggestion['candidates'][0]['confidence']==.5 and not pi.buffers['ai']['text']
    payload=dict(request_id='correct-event',epoch=pi.epoch,candidate_id='event-low',expected_revision=0,label='xin_chao')
    pi.select_sign(payload);pi.select_sign(payload)
    assert pi.buffers['ai']['text']=='Xin chào' and not pi.pending
    with pi.store.connect() as db:
        rows=db.execute('SELECT * FROM recognition_corrections').fetchall()
    assert len(rows)==1 and rows[0]['predicted']=='an_com' and rows[0]['selected']=='xin_chao' and rows[0]['confidence']==.5
    pi.select_sign(dict(payload,request_id='replace-last',candidate_id=None,expected_revision=1,label='an_com',operation='replace_last'))
    assert pi.buffers['ai']['text']=='Ăn cơm'
    pi.select_sign(dict(payload,request_id='delete-last',candidate_id=None,expected_revision=2,operation='delete_last'))
    assert pi.buffers['ai']['text']==''
    with pytest.raises(Exception):pi.select_sign(dict(payload,request_id='stale-correction',expected_revision=0))


def test_search_requires_selected_location_and_explicit_places_opt_in(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Unexpected network call')
    monkeypatch.setattr('assistant.urlopen',forbidden)
    monkeypatch.delenv('DAKT_PLACES_ENABLED',raising=False)
    monkeypatch.delenv('GOOGLE_PLACES_API_KEY',raising=False)
    assert place_query('tìm ăn cơm')=='quán cơm'
    assert place_query('tìm ATM')=='ATM'
    result=_search('tìm ăn cơm',None)
    assert not result['items'] and 'Chọn vị trí' in result['message']
    result=_search('tìm ăn cơm',dict(label='Trường của tôi'))
    assert not result['items'] and 'NOT_CONFIGURED' in result['message'] and result['maps_url'].startswith('https://www.google.com/maps/search/')


def test_places_real_source_schema_distance_and_network_failure(monkeypatch):
    monkeypatch.setenv('DAKT_PLACES_ENABLED','1');monkeypatch.setenv('GOOGLE_PLACES_API_KEY','test-only')
    def response(request,timeout):
        payload=json.loads(request.data)
        assert payload['textQuery']=='quán cơm' and payload['pageSize']==3 and payload['rankPreference']=='DISTANCE'
        assert 'X-goog-api-key' in request.headers
        return BytesIO(json.dumps({'places':[{'id':'place-test','displayName':{'text':'Tên do Places trả'},
             'formattedAddress':'Địa chỉ từ Places','location':{'latitude':10.0,'longitude':106.0}}]}).encode())
    monkeypatch.setattr('assistant.urlopen',response)
    result=_search('tìm ăn cơm',dict(lat=10.0,lon=106.0,label='Vị trí được chọn'))
    assert result['source']=='Google Places' and result['items'][0]['distance_m']==0
    assert len(result['items'])==1 and result['items'][0]['name']=='Tên do Places trả'
    def fail(*args,**kwargs):raise HTTPError('secret-key',403,'secret-key',{},None)
    monkeypatch.setattr('assistant.urlopen',fail)
    result=_search('tìm ăn cơm',dict(lat=10.0,lon=106.0))
    assert not result['items'] and 'secret' not in result['message']


def test_search_api_without_provider_and_invalid_coordinates(tmp_path,monkeypatch):
    monkeypatch.setattr('server.ROOT',tmp_path)
    app=create_app(tmp_path/'search.sqlite3');app.state.pi.provider=None
    with TestClient(app) as client:
        body=dict(request_id='search-no-key',epoch=app.state.pi.epoch,text='tìm ăn cơm',task='search',location=dict(label='Trường của tôi'))
        assert client.post('/api/pi/question',json=body).status_code==202
        assert client.post('/api/pi/question',json=dict(body,request_id='search-bad-lat',location=dict(lat=100,lon=0))).status_code==422


def test_gemini_503_bounded_retry_never_leaks_or_changes_model(monkeypatch):
    calls=[];sleeps=[]
    def fail(request,timeout):
        calls.append(request.full_url)
        raise HTTPError('secret',503,'secret',{},None)
    monkeypatch.setattr('ai_provider.urlopen',fail);monkeypatch.setattr('ai_provider.sleep',sleeps.append)
    with pytest.raises(AIError,match='503'):GeminiProvider('test-only')._answer('Xin chào')
    assert len(calls)==2 and len(sleeps)==1 and len(set(calls))==1


@pytest.mark.parametrize('text,query', [('Tìm ăn cơm.','quán cơm'),('Tìm quán cà phê','quán cà phê'),('Tìm quán cơm gần đây','quán cơm'),('Tìm nhà thuốc','nhà thuốc'),('Tìm bệnh viện','bệnh viện'),('Tôi muốn ăn','quán ăn')])
def test_search_intents(text,query):
    assert place_query(text)==query


def test_places_sort_filter_deduplicate_and_bound_speech(monkeypatch):
    from assistant import place_speech
    monkeypatch.setenv('DAKT_PLACES_ENABLED','1');monkeypatch.setenv('GOOGLE_PLACES_API_KEY','test-only')
    def item(identifier,lat):return dict(id=identifier,displayName=dict(text=identifier),formattedAddress='Địa chỉ từ nguồn kiểm thử',location=dict(latitude=lat,longitude=106))
    def response(*args,**kwargs):return BytesIO(json.dumps({'places':[item('Xa',11),item('Gần',10.001),item('Gần',10.001)]}).encode())
    monkeypatch.setattr('assistant.urlopen',response)
    result=_search('cơm',dict(lat=10,lon=106))
    assert result['status']=='ok' and result['searched_at'] and [i['name'] for i in result['items']]==['Gần']
    spoken=place_speech(result['items'])
    assert 'Địa chỉ từ nguồn kiểm thử' in spoken and 'gần nhất' not in spoken and 'mét' not in spoken


def test_search_auto_speech_once_and_replay_through_existing_protocol(tmp_path,monkeypatch):
    from test_pi_modes import FakeMQTT, reply, sample_wav
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'search-tts.sqlite3').state.pi
    pi.mqtt=FakeMQTT();pi.tts.ready=True
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL','http://pi-test.local:8001')
    spoken=[]
    monkeypatch.setattr(pi.tts,'synthesize_cloud',lambda text, voice, speed:spoken.append(text) or sample_wav())
    async def search(*args):return dict(status='ok',source='© OpenStreetMap contributors',items=[dict(name='Tên từ nguồn kiểm thử',address='Địa chỉ kiểm thử')],message='Nguồn kiểm thử',searched_at='2026-11-03T12:00:00+00:00')
    monkeypatch.setattr('pi_modes.search_places',search)
    payload=dict(request_id='search-auto-once',epoch=pi.epoch,text='tìm cơm',task='search',read_results=True)
    async def scenario():
        pi.ask(payload);pi.ask(payload);await pi.task
        assert pi.ai['status']=='done' and pi.speech['status']=='pending' and len(spoken)==1
        assert [kind for kind,_ in pi.mqtt.sent].count('speech')==1
        for status in ['ACK','PLAYING','DONE']:pi.on_status(reply(pi,'speech',status))
        for _ in range(4):pi.snapshot();pi.tick();pi.ask(payload)
        assert len(spoken)==1
        pi.speak(dict(request_id='search-manual-replay',epoch=pi.epoch,text=pi.ai['answer']));await pi.task
        assert len(spoken)==1  # Read-again reuses the WAV cache.
    asyncio.run(scenario())
    assert not any(kind=='command' for kind,_ in pi.mqtt.sent)


@pytest.mark.parametrize('status,read_results,mqtt,expected', [('not_configured',True,True,'idle'),('empty',True,True,'idle'),('error',True,True,'idle'),('ok',False,True,'idle'),('ok',True,False,'error')])
def test_search_missing_results_optout_offline_keep_draft(tmp_path,monkeypatch,status,read_results,mqtt,expected):
    from test_pi_modes import FakeMQTT
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'search-offline.sqlite3').state.pi;pi.mqtt=FakeMQTT();pi.mqtt.connected=mqtt
    pi.mqtt.error='MQTT offline';pi.write_buffer('ai','Câu gốc')
    async def search(*args):return dict(status=status,source='© OpenStreetMap contributors',items=[dict(name='Tên kiểm thử',address='Địa chỉ kiểm thử')] if status=='ok' else [],message='Không có kết quả thật')
    monkeypatch.setattr('pi_modes.search_places',search)
    async def scenario():
        pi.ask(dict(request_id='search-result-guard',epoch=pi.epoch,text='tìm cơm',task='search',read_results=read_results));await pi.task
        assert pi.ai['status']=='done' and pi.speech['status']==expected
        assert pi.buffers['ai']['text']=='Câu gốc' and not pi.pending
    asyncio.run(scenario())


def test_ambiguous_search_uses_provider_only_when_configured(monkeypatch):
    monkeypatch.setenv('DAKT_PLACE_PROVIDER','google')
    from assistant import search_places
    calls=[]
    class Provider:
        async def answer(self,text):calls.append(text);return '{"query":"nhà thuốc"}'
    async def scenario():
        result=await search_places('tôi cần mua thuốc cho bà',dict(lat=10,lon=106),Provider())
        assert result['status']=='not_configured' and not calls
        monkeypatch.setenv('DAKT_PLACES_ENABLED','1');monkeypatch.setenv('GOOGLE_PLACES_API_KEY','test-only')
        monkeypatch.setattr('assistant.urlopen',lambda *args,**kwargs:BytesIO(b'{"places":[]}'))
        result=await search_places('cần mua băng gạc',dict(lat=10,lon=106),Provider())
        assert result['query']=='nhà thuốc' and len(calls)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('text,expected', [
 ('TÌM QUÁN CƠM GẦN ĐÂY','search'),('Tìm nhà thuốc gần đây.','search'),
 ('Tìm ăn cơm địa chỉ','search'),('Địa chỉ quán cơm','search'),('Tìm nhà hàng gần đây','search'),
 ('Tìm quán cà phê','search'),('Bệnh viện ở đâu?','search'),
 ('Tôi đang ăn cơm','rewrite'),('Tìm hiểu về quán cơm là gì?','question'),
 ('Một ngày có bao nhiêu giờ?','question'),('Xin chào','rewrite'),
])
def test_auto_routing_does_not_confuse_place_search_and_rewrite(text,expected):
    from assistant import resolve_task
    assert resolve_task(text,'auto')==expected
    assert resolve_task(text,'rewrite')=='rewrite'
    assert resolve_task(text,'question')=='question'


@pytest.mark.parametrize('provider,read,expected', [('gemini', True, 1), ('groq', True, 1),
                                                  ('gemini', False, 0), ('mock', True, 0)])
def test_question_autoplay_deduplicates_and_keeps_full_answer(tmp_path, monkeypatch, provider, read, expected):
    from test_pi_modes import FakeMQTT, reply, sample_wav
    pi = create_app(tmp_path/'question-speech.sqlite3').state.pi
    pi.mqtt = FakeMQTT()
    pi.tts.ready = True
    full_answer = 'Xin chào bạn. ' * 80
    class Provider:
        name = provider
        async def answer(self, text):
            return full_answer
    pi.provider = Provider()
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://pi-test.local:8001')
    spoken = []
    monkeypatch.setattr(pi.tts, 'synthesize_cloud', lambda text, voice, speed: spoken.append(text) or sample_wav())
    payload = dict(request_id='question-once', epoch=pi.epoch, text='Xin chào', task='question', read_results=read)
    async def scenario():
        pi.ask(payload)
        pi.ask(payload)
        await pi.task
        assert pi.ai['answer'] == full_answer
        if expected:
            assert pi.speech['request_id'] == payload['request_id']
            for status in ('ACK', 'PLAYING', 'DONE'):
                pi.on_status(reply(pi, 'speech', status))
        pi.snapshot()
        pi.ask(payload)
        assert len(spoken) == expected
        assert all(len(text) <= 550 and text.endswith('.') for text in spoken)
    asyncio.run(scenario())


def test_auto_search_api_routes_without_provider_and_preserves_draft(tmp_path,monkeypatch):
    monkeypatch.setattr('server.ROOT',tmp_path)
    app=create_app(tmp_path/'auto-route.sqlite3');pi=app.state.pi;pi.provider=None
    pi.write_buffer('ai','Câu chưa gửi')
    with TestClient(app) as client:
        response=client.post('/api/pi/question',json=dict(request_id='auto-place-route',epoch=pi.epoch,text='TÌM QUÁN CƠM GẦN ĐÂY',task='auto',read_results=True,location=dict(label='Vị trí người dùng chọn')))
        assert response.status_code==202
        assert response.json()['pi']['ai']['task']=='search'
        assert pi.buffers['ai']['text']=='Câu chưa gửi' and not pi.pending


def test_explicit_rewrite_ignores_search_autoplay_flag(tmp_path,monkeypatch):
    monkeypatch.setattr('server.ROOT',tmp_path)
    pi=create_app(tmp_path/'explicit-rewrite.sqlite3').state.pi
    class Provider:
        async def answer(self,text):return 'Tìm quán cơm gần đây.'
    pi.provider=Provider()
    async def scenario():
        pi.ask(dict(request_id='rewrite-place-explicit',epoch=pi.epoch,text='TÌM QUÁN CƠM GẦN ĐÂY',task='rewrite',read_results=True))
        await pi.task
        assert pi.ai['task']=='rewrite' and pi.ai['proposal']=='Tìm quán cơm gần đây.'
        assert pi.speech['status']=='idle' and not pi.pending
    asyncio.run(scenario())


@pytest.mark.parametrize('code,expected',[(400,'INVALID_REQUEST'),(401,'UNAUTHENTICATED'),(403,'PERMISSION_DENIED'),(429,'QUOTA_EXCEEDED'),(503,'UNAVAILABLE')])
def test_places_reports_safe_http_reason(monkeypatch,code,expected):
    monkeypatch.setenv('DAKT_PLACES_ENABLED','1');monkeypatch.setenv('GOOGLE_PLACES_API_KEY','private-not-for-response')
    def fail(*args,**kwargs):raise HTTPError('private-not-for-response',code,'secret body',{},None)
    monkeypatch.setattr('assistant.urlopen',fail)
    result=_search('TÌM QUÁN CƠM GẦN ĐÂY',dict(lat=10,lon=106))
    assert result['status']=='error' and result['error_code']==expected and result['http_status']==code and not result['items']
    assert 'private-not-for-response' not in json.dumps(result) and 'secret body' not in json.dumps(result)


@pytest.mark.parametrize('failure,expected',[(TimeoutError('private timeout'),'TIMEOUT'),(OSError('private invalid response'),'INVALID_RESPONSE')])
def test_places_timeout_and_failure_never_leak(monkeypatch,failure,expected):
    monkeypatch.setenv('DAKT_PLACES_ENABLED','1');monkeypatch.setenv('GOOGLE_PLACES_API_KEY','private-test')
    def fail(*args,**kwargs):raise failure
    monkeypatch.setattr('assistant.urlopen',fail)
    result=_search('tìm cơm tấm gần tôi',dict(lat=10,lon=106))
    assert result['error_code']==expected and not result['items'] and 'private' not in json.dumps(result)
    assert place_query('tìm cơm tấm gần tôi')=='quán cơm tấm'


def test_places_minimal_fields_and_no_provider_id_required(monkeypatch):
    monkeypatch.setenv('DAKT_PLACES_ENABLED','1');monkeypatch.setenv('GOOGLE_PLACES_API_KEY','test-only')
    item={'displayName':{'text':'TEST restaurant'},'formattedAddress':'TEST address','location':{'latitude':10.001,'longitude':106}}
    def response(request,timeout):
        assert request.get_header('X-goog-fieldmask')=='places.displayName,places.formattedAddress,places.location'
        body=json.loads(request.data);assert body['pageSize']==3 and body['locationBias']['circle']['radius']==5000
        return BytesIO(json.dumps({'places':[item,item]}).encode())
    monkeypatch.setattr('assistant.urlopen',response)
    result=_search('quán ăn gần đây',dict(lat=10,lon=106))
    assert result['status']=='ok' and len(result['items'])==1 and result['items'][0]['name']=='TEST restaurant'
