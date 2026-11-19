import asyncio
from io import BytesIO
import json
from time import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from assistant import place_query, place_speech, search_places
from geoapify_places import GeoapifyPlaces


@pytest.mark.parametrize(('text','category'), [
    ('Tìm ăn cơm', 'catering.food_court'), ('Tìm quán cà phê', 'catering.cafe'),
    ('Tìm quán nước', 'catering.cafe'), ('Tìm nhà thuốc', 'healthcare.pharmacy'),
    ('Tìm bệnh viện', 'healthcare.hospital'), ('Tìm ATM', 'service.financial.atm'),
])
def test_category_radius_dedup_address_and_cache(monkeypatch, text, category):
    calls = []

    def respond(request, timeout):
        params = parse_qs(urlsplit(request.full_url).query)
        assert timeout == 4 and category in params['categories'][0].split(',')
        assert 'name' not in params and params['limit'] == ['20']
        calls.append(params['filter'][0])
        p = {'lat': 10.02, 'lon': 106, 'name': 'Tên được báo', 'place_id': 'real-id'}
        rows = [] if len(calls) == 1 else [{'properties': p}, {'properties': p}]
        return BytesIO(json.dumps({'features': rows}).encode())

    monkeypatch.setattr('geoapify_places.open_places', respond)
    service = GeoapifyPlaces()
    location = {'lat': 10, 'lon': 106}
    query = place_query(text)
    result = service.search(query, location, 'test-key')
    assert len(result['items']) == 1 and result['items'][0]['address'] == 'Thiếu địa chỉ chi tiết'
    assert 'Tên được báo' in place_speech(result['items'])
    cached = service.search(query, location, 'test-key')
    assert cached['cached'] and cached['searched_at'] == result['searched_at']
    assert calls == ['circle:106,10,1500', 'circle:106,10,3000']


@pytest.mark.parametrize(('status','count','code'), [(429,1,'QUOTA_EXCEEDED'), (503,2,'UNAVAILABLE')])
def test_retry_circuit_and_secret_redaction(monkeypatch, status, count, code):
    calls = []

    def fail(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, status, 'Sensitive URL', {}, BytesIO())

    monkeypatch.setattr('geoapify_places.open_places', fail)
    monkeypatch.setattr('geoapify_places.sleep', lambda _: None)
    service = GeoapifyPlaces()
    for query in ('ATM', 'bệnh viện'):
        result = service.search(query, {'lat': 10, 'lon': 106}, 'test-key')
        assert result['error_code'] == code and 'test-key' not in str(result)
        assert not result['items'] and place_speech(result['items']) == ''
    assert len(calls) == count


def test_missing_expired_or_inaccurate_phone_no_lookup(monkeypatch):
    monkeypatch.setenv('DAKT_PLACE_PROVIDER', 'geoapify')
    monkeypatch.setattr('geoapify_places.open_places', lambda *a, **k: pytest.fail('Unexpected network'))
    phone = {'source':'phone', 'lat':10, 'lon':106, 'accuracy':20, 'timestamp': time()*1000}
    for position in (None, {**phone, 'timestamp':time()*1000-901000}, {**phone, 'accuracy':501}):
        assert asyncio.run(search_places('Tìm ATM', position))['error_code'] == 'LOCATION_REQUIRED'


def test_empty_has_no_speech(monkeypatch):
    monkeypatch.setattr('geoapify_places.open_places', lambda *a, **k: BytesIO(b'{"features":[]}'))
    result = GeoapifyPlaces().search('quán ăn', {'lat': 10, 'lon': 106}, 'test-key')
    assert result['status'] == 'empty' and place_speech(result['items']) == ''


@pytest.mark.parametrize('status', ['ok', 'error'])
def test_search_only_publishes_speech_for_valid_places(tmp_path, monkeypatch, status):
    from server import create_app
    from test_pi_modes import FakeMQTT, sample_wav

    monkeypatch.setenv('DAKT_PLACE_PROVIDER', 'geoapify')
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://pi-test.local:8001')
    pi = create_app(tmp_path / 'test.sqlite3').state.pi
    pi.mqtt = FakeMQTT()
    pi.location.device['phone'] = {'source':'phone', 'lat':10, 'lon':106, 'accuracy':20, 'timestamp': time()*1000}
    spoken = []

    async def lookup(text, location, provider):
        assert text == 'Tìm ăn cơm' and location['source'] == 'phone'
        return {'status': status, 'source': 'Geoapify', 'message': 'Kết quả kiểm thử',
                'items': [{'name':'Quán mẫu', 'address':'12 Đường Mẫu'}] if status == 'ok' else []}

    monkeypatch.setattr('pi_modes.search_places', lookup)
    monkeypatch.setattr(pi.tts, 'synthesize_cloud', lambda text, *_: spoken.append(text) or sample_wav())

    async def scenario():
        pi.ask({'request_id':'places-speech-test', 'epoch':pi.epoch, 'text':'Tìm ăn cơm',
                'task':'auto', 'read_results':True})
        await pi.task

    asyncio.run(scenario())
    assert len(spoken) == (1 if status == 'ok' else 0)
    assert len([kind for kind, _ in pi.mqtt.sent if kind == 'speech']) == len(spoken)
    if spoken:
        assert 'Quán mẫu' in spoken[0] and '12' in spoken[0] and 'Đường Mẫu' in spoken[0]


def test_named_address_uses_geocoding_and_returns_one_fact(monkeypatch):
    from assistant import named_place_query, resolve_task
    query = named_place_query('Tìm trường Đại học Công nghiệp')
    assert query == 'trường Đại học Công nghiệp'
    assert resolve_task('Tôi muốn ăn cơm','auto') == 'rewrite'
    assert resolve_task('Địa chỉ trường Đại học Công nghiệp','auto') == 'search'
    assert named_place_query('Tìm nhà thuốc') is None
    assert named_place_query('Địa chỉ quán cà phê Mộc') == 'quán cà phê Mộc'
    def respond(request, timeout):
        url=urlsplit(request.full_url)
        assert url.path == '/v1/geocode/search'
        assert parse_qs(url.query)['text'] == [query]
        return BytesIO(json.dumps({'features':[{'properties':{
            'name':'Tên từ provider','formatted':'12 Đường kiểm thử','street':'Đường kiểm thử',
            'housenumber':'12','lat':10.01,'lon':106}}]}).encode())
    monkeypatch.setattr('geoapify_places.open_places',respond)
    result=GeoapifyPlaces().search(query,{'lat':10,'lon':106},'test-key')
    assert result['status']=='ok' and len(result['items'])==1
    spoken=place_speech(result['items'],result)
    assert spoken=='Tên từ provider. Địa chỉ: 12 Đường kiểm thử.'
    assert 'Geoapify' not in spoken and '2026' not in spoken
