import asyncio
from io import BytesIO
import json
import pytest
from fastapi.testclient import TestClient
from server import Store,create_app
from location_service import LocationService


def test_geocode_validated_results_require_explicit_confirmation(tmp_path,monkeypatch):
    service=LocationService(Store(tmp_path/'locations.sqlite3'));calls=[]
    def response(request,timeout):
        calls.append(request.full_url)
        assert request.full_url.startswith('https://geocoding-api.open-meteo.com/v1/search?') and timeout==8
        return BytesIO(json.dumps({'results':[{'name':'TEST city','admin1':'TEST region','country':'TEST country','latitude':10,'longitude':106},
            {'name':'invalid','latitude':999,'longitude':106},{'name':'invalid','latitude':'10','longitude':106}]}).encode())
    monkeypatch.setattr('location_service.urlopen',response)
    result=asyncio.run(service.geocode('TEST city'))
    assert result['items']==[{'label':'TEST city, TEST region, TEST country','lat':10,'lon':106}]
    assert service.revision==0 and service.snapshot()['current'] is None
    with pytest.raises(Exception) as issue:asyncio.run(service.geocode('TEST city'))
    assert issue.value.status_code==429 and len(calls)==1


@pytest.mark.parametrize('data',[{}, {'results':[{'name':'invalid','latitude':None,'longitude':106}]}])
def test_geocode_empty_never_invents_location(tmp_path,monkeypatch,data):
    monkeypatch.setattr('location_service.urlopen',lambda *a,**k:BytesIO(json.dumps(data).encode()))
    result=asyncio.run(LocationService(Store(tmp_path/'empty.sqlite3')).geocode('TEST region'))
    assert result['items']==[] and 'Không tìm thấy' in result['message']


def test_geocode_network_error_keeps_provider_details_private(tmp_path,monkeypatch):
    def failed(*args,**kwargs):raise OSError('private query/url')
    monkeypatch.setattr('location_service.urlopen',failed)
    with pytest.raises(Exception) as issue:asyncio.run(LocationService(Store(tmp_path/'error.sqlite3')).geocode('TEST region'))
    assert issue.value.status_code==502 and 'private' not in issue.value.detail


def test_geocode_api_auth_and_validation(tmp_path,monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN','test-pairing')
    client=TestClient(create_app(tmp_path/'auth.sqlite3'))
    monkeypatch.setattr('location_service.urlopen',lambda *a,**k:pytest.fail('Validation must not call provider'))
    assert client.post('/api/location/search',json={'name':'TEST city'}).status_code==401
    for name in [' ', 'aa', 'x'*161]:
        assert client.post('/api/location/search',json={'name':name},headers={'Authorization':'Bearer test-pairing'}).status_code==422
