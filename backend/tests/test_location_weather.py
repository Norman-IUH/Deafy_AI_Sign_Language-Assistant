import asyncio
from datetime import datetime,timedelta
from io import BytesIO
import json
from time import time
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from server import Store,create_app
from location_service import LocationService
from weather import WeatherService
from assistant import resolve_task


def position(revision=0,source='phone',**extra):
    return dict(request_id='location-'+str(revision),expected_revision=revision,lat=10.,lon=106.,accuracy=20.,timestamp=time()*1000,source=source,label='TEST REFERENCE',**extra)


def test_location_priority_persistence_expiry_and_clear(tmp_path,monkeypatch):
    store=Store(tmp_path/'location.sqlite3');service=LocationService(store)
    manual=position(source='manual');service.update(manual);service.update(manual)
    assert service.revision==1
    service.update(position(1,source='phone'))
    service.update(position(2,source='browser'))
    assert service.snapshot()['current']['source']=='phone'
    restored=LocationService(store);assert restored.snapshot()==service.snapshot()
    assert restored.resolve(source='phone')['source']=='phone'
    assert restored.resolve(source='manual')['source']=='manual'
    monkeypatch.setattr('location_service.time',lambda:time()+901)
    assert restored.snapshot()['current']['source']=='manual'
    assert restored.resolve(source='phone') is None
    restored.update(dict(request_id='clear-location',expected_revision=3),clear=True)
    assert not restored.snapshot()['current'] and not restored.snapshot()['has_saved']
    assert not LocationService(store).snapshot()['current']


@pytest.mark.parametrize('change',[{'accuracy':501},{'timestamp':0},{'timestamp':time()*1000+120000},{'accuracy':None}])
def test_location_rejects_stale_inaccurate_or_future(tmp_path,change):
    service=LocationService(Store(tmp_path/'location.sqlite3'))
    with pytest.raises(Exception):service.update({**position(),**change})
    assert service.revision==0


def test_location_api_auth_validation_and_conflicts(tmp_path,monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN','test-access-private')
    app=create_app(tmp_path/'api.sqlite3');client=TestClient(app)
    assert client.post('/api/location',json=position()).status_code==401
    headers={'Authorization':'Bearer test-access-private'}
    assert client.post('/api/location',headers=headers,json={**position(),'lat':91}).status_code==422
    response=client.post('/api/location',headers=headers,json=position())
    assert response.status_code==200 and response.json()['pi']['location']['current']['source']=='phone'
    assert client.post('/api/location',headers=headers,json=position(0,source='manual')).status_code==409
    assert client.request('DELETE','/api/location',headers=headers,json={'request_id':'clear-location','expected_revision':1}).status_code==200
    assert app.state.store.snapshot()['history_count']==0


def weather_data():
    now=datetime.now(ZoneInfo('Asia/Ho_Chi_Minh'))
    return dict(timezone='Asia/Ho_Chi_Minh',current={'time':now.strftime('%Y-%m-%dT%H:%M'),'temperature_2m':28,'relative_humidity_2m':70,'weather_code':2},
                current_units={'temperature_2m':'°C','relative_humidity_2m':'%'},daily={'time':[now.date().isoformat()],'precipitation_probability_max':[60]})


def test_weather_uses_real_schema_units_local_day_and_cache(monkeypatch):
    calls=[]
    def response(request,timeout):
        calls.append(request.full_url)
        assert request.full_url.startswith('https://api.open-meteo.com/v1/forecast?') and timeout==8
        assert 'timezone=auto' in request.full_url and 'relative_humidity_2m' in request.full_url
        return BytesIO(json.dumps(weather_data()).encode())
    monkeypatch.setattr('weather.urlopen',response)
    service=WeatherService();loc={'lat':10,'lon':106,'label':'TEST REFERENCE'}
    result=service.lookup(loc)
    assert result['status']=='ok' and result['current']['temperature_2m']==28
    assert result['condition']=='Có mây rải rác' and result['label']=='TEST REFERENCE'
    assert result['observed_at'].endswith('+07:00')
    assert '60 phần trăm' in result['message'] and result['daily']['temperature_2m_min'] is None
    assert service.lookup(loc)['cached'] and len(calls)==1
    assert 'lat' not in result and 'lon' not in result


@pytest.mark.parametrize('bad',['stale','wrong_day','missing_temperature','wrong_units','network'])
def test_weather_missing_or_bad_data_never_guesses(monkeypatch,bad):
    data=weather_data()
    if bad=='stale':data['current']['time']='2000-01-01T00:00'
    if bad=='wrong_day':data['daily']['time']=['2000-01-01']
    if bad=='missing_temperature':data['current'].pop('temperature_2m')
    if bad=='wrong_units':data['current_units']['temperature_2m']='°F'
    def response(*args,**kwargs):
        if bad=='network':raise OSError('coordinates/private URL must not escape')
        return BytesIO(json.dumps(data).encode())
    monkeypatch.setattr('weather.urlopen',response)
    result=WeatherService().lookup({'lat':10,'lon':106})
    assert result['status']=='error' and 'private' not in result['message'] and 'current' not in result


@pytest.mark.parametrize('text',['Thời tiết hôm nay','Hôm nay có mưa không?','Ngoài trời bao nhiêu độ?','Thời tiết chỗ tôi hiện tại'])
def test_weather_routing(text):assert resolve_task(text,'auto')=='weather'


def test_weather_does_not_call_llm_and_autoplays_once(tmp_path,monkeypatch):
    from test_pi_modes import FakeMQTT, reply, sample_wav
    pi=create_app(tmp_path/'weather.sqlite3').state.pi;pi.provider=None;pi.mqtt=FakeMQTT();pi.tts.ready=True
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL','http://pi-test.local:8001')
    pi.location.update(position(source='manual'))
    spoken=[];monkeypatch.setattr(pi.tts,'synthesize_cloud',lambda text, voice, speed:spoken.append(text) or sample_wav())
    async def lookup(location):
        assert location['label']=='TEST REFERENCE'
        return {'status':'ok','source':'Open-Meteo','message':'DỮ LIỆU KIỂM THỬ: 28 độ C','current':{'temperature_2m':28}}
    monkeypatch.setattr(pi.weather,'get',lookup)
    payload=dict(request_id='weather-once',epoch=pi.epoch,text='Thời tiết hôm nay',task='auto',read_results=True)
    async def scenario():
        pi.ask(payload);pi.ask(payload);await pi.task
        assert pi.ai['provider']=='open-meteo' and len(spoken)==1
        for status in ['ACK','PLAYING','DONE']:pi.on_status(reply(pi,'speech',status))
        pi.ask(payload);assert len(spoken)==1
    asyncio.run(scenario())
    assert not any(kind=='command' for kind,_ in pi.mqtt.sent)


def test_no_location_no_network_or_playback(tmp_path,monkeypatch):
    pi=create_app(tmp_path/'missing.sqlite3').state.pi;pi.provider=None
    monkeypatch.setattr('weather.urlopen',lambda *a,**k:pytest.fail('Unexpected network'))
    async def scenario():
        pi.ask(dict(request_id='weather-missing',epoch=pi.epoch,text='Thời tiết hôm nay',task='auto',read_results=True))
        await pi.task
    asyncio.run(scenario())
    assert pi.ai['search']['status']=='location_required' and pi.speech['status']=='idle'
    assert resolve_task('Thời tiết là gì?','auto')=='question'


def test_partial_coordinates_do_not_leave_processing_or_write_history(tmp_path):
    pi=create_app(tmp_path/'partial.sqlite3').state.pi
    payload=dict(request_id='invalid-partial',epoch=pi.epoch,text='Thời tiết hôm nay',task='weather',location={'lat':10,'lon':None})
    with pytest.raises(Exception):pi.ask(payload)
    assert pi.ai['status']=='idle' and payload['request_id'] not in pi.requests
    assert pi.store.snapshot()['history_count']==0
