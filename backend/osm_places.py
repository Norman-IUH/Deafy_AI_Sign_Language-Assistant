"""Small user-triggered Overpass queries with a bounded retry."""
import asyncio
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import re
from random import uniform
from time import time,monotonic,sleep
import unicodedata
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.lower()) if not unicodedata.combining(c)).replace('đ','d')


class OSMPlaces:
    def __init__(self,cache_path=None, *, limited=False):
        self.path=Path(cache_path) if cache_path else None
        self.cache={};self.last_request=float('-inf')
        self.blocked_until = 0
        self.limited = limited
        if self.path and self.path.is_file():
            try:
                if self.path.stat().st_size<=262144:
                    data=json.loads(self.path.read_text(encoding='utf-8'))
                    if isinstance(data,dict):
                        for key,entry in list(data.items())[-16:]:
                            if not isinstance(entry,dict) or not isinstance(entry.get('result'),dict):continue
                            value=entry['result']
                            items=value.get('items',[])
                            if type(entry.get('time')) in (int,float) and value.get('status')=='ok' and value.get('source')=='© OpenStreetMap contributors' and isinstance(value.get('searched_at'),str) and isinstance(items,list) and 0<len(items)<=3 and all(isinstance(item,dict) and all(isinstance(item.get(k),str) and 0<len(item[k])<=350 for k in ('name','address')) for item in items):self.cache[key]=entry
            except (OSError,ValueError):pass

    def lookup(self,text,location):
        from assistant import place_query,distance_m
        query=place_query(text)
        result={'query':query,'items':[],'status':'error','source':'© OpenStreetMap contributors',
                'searched_at':datetime.now(timezone.utc).isoformat(),'cached':False,'stale':False}
        def fail(code,message):return {**result,'error_code':code,'message':message}
        lat,lon=(location or {}).get('lat'),(location or {}).get('lon')
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (lat,lon)) or not -90<=lat<=90 or not -180<=lon<=180:
            return {**fail('LOCATION_REQUIRED','LOCATION_REQUIRED · Chọn/cấp quyền vị trí hoặc xác nhận khu vực trong Cài đặt.'),'status':'needs_location'}
        result['maps_url'] = f'https://www.openstreetmap.org/#map=16/{lat:.3f}/{lon:.3f}'
        kinds={'quán cơm':'restaurant|fast_food|food_court','quán cơm tấm':'restaurant|fast_food|food_court','quán ăn':'restaurant|fast_food|food_court',
               'quán cà phê':'cafe','nhà thuốc':'pharmacy','bệnh viện':'hospital','ATM':'atm'}
        if query not in kinds:return fail('UNSUPPORTED_QUERY','Chọn loại cụ thể: quán ăn, quán cơm, quán cà phê, nhà thuốc hoặc bệnh viện.')
        key=f'{lat:.4f},{lon:.4f}:{query}';cached=self.cache.get(key)
        age=time()-cached['time'] if cached else float('inf')

        def collect(data):
            seen=set();items=[]
            for element in data['elements']:
                tags=element.get('tags',{});name=tags.get('name:vi') or tags.get('name')
                if data.get('snapshot_at') and tags.get('amenity') not in kinds[query].split('|'):
                    continue
                if not isinstance(name,str) or not name.strip() or len(name)>160:continue
                if query in ('quán cơm','quán cơm tấm'):
                    evidence=normalized(name+' '+str(tags.get('cuisine','')))
                    if not re.search(r'(?:^|[^a-z])(com|rice)(?:[^a-z]|$)',evidence):continue
                    if query=='quán cơm tấm' and not re.search(r'com[_ ]tam|broken[_ ]rice',evidence):continue
                position=element.get('center',element);a,b=position.get('lat'),position.get('lon')
                if not all(type(v) in (int,float) and math.isfinite(v) for v in (a,b)) or not -90<=a<=90 or not -180<=b<=180:continue
                distance=distance_m((lat,lon),(a,b))
                if distance>2000:continue
                def tag(k):return tags[k].strip() if isinstance(tags.get(k),str) else ''
                full,street,number=tag('addr:full'),tag('addr:street'),tag('addr:housenumber')
                complete=bool(full or street and number)
                parts=list(dict.fromkeys(p for p in [' '.join(p for p in (number,street) if p),tag('addr:suburb'),tag('addr:district'),tag('addr:city'),tag('addr:province')] if p))
                address=(full or ', '.join(parts))[:300]
                if not complete:address=(address+' · ' if address else '')+'Địa chỉ chưa đầy đủ trong OSM'
                identity=(normalized(name.strip()),round(a,4),round(b,4))
                if identity in seen:continue
                seen.add(identity);items.append({'name':name.strip(),'address':address,'address_complete':complete,'distance_m':distance})
            items.sort(key=lambda item:(not item['address_complete'],item['distance_m']))
            match={**result,'items':items[:3],'status':'ok' if items else 'empty','message':'Tối đa 3 địa điểm trong 2 km. Dữ liệu OSM có thể thiếu địa chỉ.'}
            if not items:return {**match,'error_code':'ZERO_RESULTS','message':'Không có địa điểm có tên phù hợp trong dữ liệu OSM quanh vị trí đã chọn. Không suy ra rằng thực tế không có quán.'}
            return match

        def store(result):
            self.cache[key]={'time':time(),'result':result}
            if len(self.cache)>16:self.cache.pop(next(iter(self.cache)))
            if self.path:
                try:
                    self.path.parent.mkdir(parents=True,exist_ok=True)
                    temp=self.path.with_suffix('.tmp')
                    temp.touch(mode=0o600,exist_ok=True);temp.chmod(0o600)
                    with temp.open('w',encoding='utf-8') as f:json.dump(self.cache,f,ensure_ascii=False)
                    os.replace(temp,self.path)
                except OSError:pass  # A disk-cache failure must not discard valid search results.
            return result

        def saved(stale):
            return {**cached['result'],'cached':True,'stale':stale,
                    'message':('Dữ liệu lưu trước; dịch vụ đang không sẵn sàng. ' if stale else 'Dữ liệu đã lưu trong 5 phút. ')+cached['result']['message']}
        if 0<=age<300:return saved(False)
        def unavailable(code,message):
            if self.path:
                path = self.path.with_name('osm-pois-saigon.json')
                try:
                    if path.is_file() and path.stat().st_size <= 16_000_000:
                        data = json.loads(path.read_text(encoding='utf-8'))
                        stamp = datetime.fromisoformat(data['snapshot_at'])
                        if 0 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 604800:
                            match = collect(data)
                            if match['status'] == 'ok':
                                match['snapshot_at'] = stamp.isoformat()
                                match['refresh_error'] = code
                                match['message'] += f' Bản trích xuất OSM khu vực TP.HCM từ BBBike ngày {stamp:%d/%m/%Y} (UTC).'
                                return store(match)
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    pass
            if cached and 0<=age<86400:return {**saved(True),'refresh_error':code}
            return fail(code,message)
        if monotonic() < self.blocked_until:
            return unavailable('RATE_LIMITED', 'Overpass yêu cầu chờ trước khi tìm lại.')
        if monotonic()-self.last_request<10:return unavailable('RATE_LIMITED','Chờ 10 giây trước khi tra khu vực/loại địa điểm mới.')
        self.last_request=monotonic()
        # Only fixed categories and validated numbers enter Overpass QL.
        radius = 2000 / 6371000
        lat_span = math.degrees(radius)
        area = f'around:2000,{lat},{lon}'
        if abs(lat) + lat_span < 90:
            lon_span = math.degrees(math.asin(math.sin(radius) / math.cos(math.radians(lat))))
            west, east = ((edge + 180) % 360 - 180 for edge in (lon - lon_span, lon + lon_span))
            area = f'{lat-lat_span:.6f},{west:.6f},{lat+lat_span:.6f},{east:.6f}'
        q=f'[out:json][timeout:7][maxsize:8388608];nwr({area})["amenity"~"^({kinds[query]})$"]["name"];out center 250;'
        request=Request('https://overpass-api.de/api/interpreter',data=urlencode({'data':q}).encode(),method='POST',
                        headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'SignAssist/1.0 (student demo; user-triggered small-area lookup)'})
        try:
            data = self.fetch(request)
            if data.get('remark'):
                if self.limited:
                    self.blocked_until = monotonic() + 60
                return unavailable('OVERLOADED','Overpass chưa hoàn thành truy vấn. Chờ rồi thử lại; không dùng kết quả dở dang.')
            match = collect(data)
            return store(match) if match['status'] == 'ok' else match
        except HTTPError as issue:
            if issue.code==429:return unavailable('QUOTA_EXCEEDED','Overpass đang giới hạn lượt tra. Chờ rồi thử lại.')
            if issue.code>=500:return unavailable('OVERLOADED','Overpass đang quá tải hoặc tạm ngừng. Chờ rồi thử lại.')
            return unavailable('HTTP_ERROR',f'Overpass từ chối truy vấn (HTTP {issue.code}).')
        except (TimeoutError,URLError) as issue:
            self.blocked_until = monotonic() + 60
            if isinstance(issue,TimeoutError) or isinstance(getattr(issue,'reason',None),TimeoutError):
                return unavailable('TIMEOUT','Overpass quá thời gian chờ. Chờ rồi thử lại.')
            return unavailable('NETWORK_ERROR','Không kết nối được Overpass. Kiểm tra Internet rồi thử lại.')
        except Exception:return unavailable('INVALID_RESPONSE','Không đọc được dữ liệu Overpass. Không tạo địa điểm thay thế.')

    async def search(self,text,location):return await asyncio.to_thread(self.lookup,text,location)

    def fetch(self, request):
        for attempt in range(1 if self.limited else 2):
            self.last_request = monotonic()
            delay = 2 ** attempt + uniform(0, 0.5)
            try:
                with urlopen(request, timeout=10) as response:
                    raw = response.read(1000001)
                if len(raw) > 1000000:
                    raise ValueError('oversized response')
                return json.loads(raw)
            except HTTPError as issue:
                retry_after = issue.headers.get('Retry-After', '') if issue.headers else ''
                try:
                    wait = int(retry_after) if retry_after.isdecimal() else max(0, parsedate_to_datetime(retry_after).timestamp() - time())
                except (TypeError, ValueError, OverflowError):
                    wait = 60 if issue.code == 429 else 0
                if issue.code in (429, 502, 503, 504):
                    self.blocked_until = monotonic() + wait
                if self.limited and (issue.code == 429 or issue.code >= 500):
                    self.blocked_until = monotonic() + max(60, wait)
                issue.close()
                if self.limited or attempt or issue.code not in (429, 502, 503, 504) or wait > 3:
                    raise
                delay = max(delay, wait)
            except (TimeoutError, URLError):
                if self.limited or attempt:
                    raise
            sleep(delay)
