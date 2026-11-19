import asyncio
from io import BytesIO
import json
from time import time
from urllib.error import HTTPError
import pytest
from osm_places import OSMPlaces
from assistant import search_places,place_speech

LOCATION={'lat':10.,'lon':106.}

def item(name='TEST Cơm Tấm',lat=10.001,**tags):
    return {'type':'node','id':1,'lat':lat,'lon':106.,'tags':{'name':name,'amenity':'restaurant',**tags}}

def install(monkeypatch,elements):
    calls=[]
    def respond(request,timeout):
        assert request.full_url=='https://overpass-api.de/api/interpreter' and timeout==10
        assert b'around' not in request.data and b'250' in request.data
        assert not any('key' in key.lower() for key in request.headers)
        calls.append(request);return BytesIO(json.dumps({'elements':elements}).encode())
    monkeypatch.setattr('osm_places.urlopen',respond);return calls

def test_rice_filters_real_evidence_and_does_not_invent_address(tmp_path,monkeypatch):
    elements=[item('TEST Italian',cuisine='italian'),item('TEST Cơm Tấm'),item('TEST rice',10.002,cuisine='rice',**{'addr:street':'TEST Street','addr:housenumber':'12'}),item('TEST far',11,cuisine='rice')]
    calls=install(monkeypatch,elements)
    result=OSMPlaces(tmp_path/'cache.json').lookup('tìm quán cơm',LOCATION)
    assert result['status']=='ok' and len(result['items'])==2 and len(calls)==1
    assert result['items'][0]['address']=='12 TEST Street' and result['items'][0]['address_complete']
    assert 'chưa đầy đủ' in result['items'][1]['address'] and 'Italian' not in json.dumps(result)
    assert 'OpenStreetMap' in result['source']

def test_persisted_cache_and_stale_fallback_are_labeled(tmp_path,monkeypatch):
    path=tmp_path/'cache.json';calls=install(monkeypatch,[item()]);service=OSMPlaces(path)
    first=service.lookup('quán cơm',LOCATION)
    assert service.lookup('quán cơm',LOCATION)['cached'] and len(calls)==1
    assert OSMPlaces(path).lookup('quán cơm',LOCATION)['cached'] and len(calls)==1
    monkeypatch.setattr('osm_places.time',lambda:time()+301)
    service.last_request=float('-inf')
    def fail(*args,**kwargs):raise HTTPError('private',429,'private',{},None)
    monkeypatch.setattr('osm_places.urlopen',fail)
    fallback=service.lookup('quán cơm',LOCATION)
    assert fallback['status']=='ok' and fallback['stale'] and fallback['cached'] and fallback['refresh_error']=='QUOTA_EXCEEDED'
    assert 'lưu trước' in fallback['message'] and place_speech(fallback['items'],fallback)==''
    monkeypatch.setattr('osm_places.time',lambda:time()+86401)
    service.last_request=float('-inf')
    assert service.lookup('quán cơm',LOCATION)['status']=='error'

@pytest.mark.parametrize('query,tag',[('quán cà phê','cafe'),('nhà thuốc','pharmacy'),('bệnh viện','hospital'),('quán ăn gần đây','restaurant')])
def test_categories_no_more_than_three_and_rate_limited(monkeypatch,query,tag):
    calls=install(monkeypatch,[item('TEST '+str(i),10+i*.001) for i in range(5)])
    service=OSMPlaces();result=service.lookup(query,LOCATION)
    assert len(result['items'])==3 and tag.encode() in calls[0].data
    assert service.lookup('quán cơm',LOCATION)['error_code']=='RATE_LIMITED' and len(calls)==1

@pytest.mark.parametrize('location',[None,{'lat':10,'lon':None},{'lat':float('nan'),'lon':106},{'lat':100,'lon':106}])
def test_no_valid_location_no_network(monkeypatch,location):
    monkeypatch.setattr('osm_places.urlopen',lambda *a,**k:pytest.fail('No location must not send query'))
    assert OSMPlaces().lookup('quán ăn gần đây',location)['error_code']=='LOCATION_REQUIRED'

@pytest.mark.parametrize('failure,code,count',[(429,'QUOTA_EXCEEDED',1),(503,'OVERLOADED',2),('timeout','TIMEOUT',2)])
def test_errors_bounded_retry_and_no_fake_results(monkeypatch,failure,code,count):
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        if failure=='timeout':raise TimeoutError('private coordinates/url')
        raise HTTPError('private',failure,'private body',{},None)
    monkeypatch.setattr('osm_places.urlopen',fail)
    delays=[]
    monkeypatch.setattr('osm_places.sleep',delays.append)
    result=OSMPlaces().lookup('quán ăn gần đây',LOCATION)
    assert result['error_code']==code and not result['items'] and len(calls)==count and 'private' not in json.dumps(result)
    assert len(delays)==count-1 and all(1<=delay<=1.5 for delay in delays)

def test_retry_after_blocks_other_searches(monkeypatch):
    calls=[]
    def fail(*args, **kwargs):
        calls.append(1)
        raise HTTPError('private',503,'busy',{'Retry-After':'120'},None)
    monkeypatch.setattr('osm_places.urlopen',fail)
    service=OSMPlaces()
    assert service.lookup('quán ăn gần đây',LOCATION)['error_code']=='OVERLOADED'
    assert service.lookup('quán cà phê',LOCATION)['error_code']=='RATE_LIMITED'
    assert len(calls)==1


def test_timeout_uses_dated_osm_snapshot_and_filters_category(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    def fail(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr('osm_places.urlopen', fail)
    monkeypatch.setattr('osm_places.sleep', lambda _: None)
    restaurant = item('Quán Cơm TEST', **{'addr:street': 'Đường TEST', 'addr:housenumber': '12'})
    pharmacy = item('Nhà thuốc Cơm TEST', amenity='pharmacy')
    snapshot = {'snapshot_at': datetime.now(timezone.utc).isoformat(), 'elements': [restaurant, pharmacy]}
    (tmp_path/'osm-pois-saigon.json').write_text(json.dumps(snapshot), encoding='utf-8')
    service = OSMPlaces(tmp_path/'cache.json')
    result = service.lookup('Tìm ăn cơm địa chỉ', LOCATION)
    assert result['status'] == 'ok' and result['refresh_error'] == 'TIMEOUT'
    assert result['snapshot_at'] == snapshot['snapshot_at']
    assert [place['address'] for place in result['items']] == ['12 Đường TEST']

def test_zero_results_or_partial_server_response_not_success(monkeypatch):
    install(monkeypatch,[])
    assert OSMPlaces().lookup('quán cơm',LOCATION)['error_code']=='ZERO_RESULTS'
    monkeypatch.setattr('osm_places.urlopen',lambda *a,**k:BytesIO(b'{"elements":[],"remark":"runtime error"}'))
    assert OSMPlaces().lookup('quán cơm',LOCATION)['error_code']=='OVERLOADED'

def test_default_osm_never_calls_google_or_llm(monkeypatch):
    monkeypatch.setenv('GOOGLE_PLACES_API_KEY','test-google-key');monkeypatch.setenv('DAKT_PLACES_ENABLED','1')
    monkeypatch.setattr('assistant.urlopen',lambda *a,**k:pytest.fail('Must not call Google'))
    service=OSMPlaces();install(monkeypatch,[item()]);monkeypatch.setattr('assistant.osm_places',service)
    class Provider:
        async def answer(self,*args):pytest.fail('Must not ask LLM for POI facts')
    assert asyncio.run(search_places('quán cơm',LOCATION,Provider()))['status']=='ok'

def test_way_center_and_broken_rice_cuisine(monkeypatch):
    value=item('TEST restaurant',cuisine='com_tam');value['center']={'lat':value.pop('lat'),'lon':value.pop('lon')};value['type']='way'
    install(monkeypatch,[value,value]);result=OSMPlaces().lookup('tìm cơm tấm gần tôi',LOCATION)
    assert len(result['items'])==1


def test_corrupt_cache_entries_do_not_crash_or_become_fake_results(tmp_path):
    path=tmp_path/'corrupt.json';path.write_text(json.dumps({'bad':None,'bad-result':{'time':time(),'result':None},'missing-items':{'time':time(),'result':{'status':'ok'}}}))
    assert OSMPlaces(path).cache=={}
