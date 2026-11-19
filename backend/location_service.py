"""One shared, consent-based reference; no movement history or IP geolocation."""
import asyncio
import json
import math
from time import time,monotonic
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from fastapi import HTTPException


class LocationService:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS shared_location (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, manual TEXT, device TEXT)')
            db.execute('INSERT OR IGNORE INTO shared_location(id,revision) VALUES(1,0)')
            row = db.execute('SELECT * FROM shared_location WHERE id=1').fetchone()
        self.revision = row['revision']
        self.manual = json.loads(row['manual']) if row['manual'] else None
        self.device = json.loads(row['device']) if row['device'] else {}
        self.requests = {}
        self.last_geocode = float('-inf')

    async def geocode(self, name):
        if monotonic()-self.last_geocode<2:raise HTTPException(429,'Chờ hai giây trước khi tìm khu vực tiếp.')
        self.last_geocode=monotonic()
        def lookup():
            try:
                query=urlencode({'name':name,'count':3,'language':'vi','format':'json'})
                with urlopen(Request('https://geocoding-api.open-meteo.com/v1/search?'+query,headers={'User-Agent':'SignAssist/1.0'}),timeout=8) as response:
                    raw=response.read(100001)
                if len(raw)>100000:raise ValueError('oversized response')
                data=json.loads(raw);items=[]
                for row in data.get('results',[])[:3]:
                    lat,lon=row.get('latitude'),row.get('longitude')
                    if not all(type(v) in (int,float) and math.isfinite(v) for v in (lat,lon)) or not -90<=lat<=90 or not -180<=lon<=180:continue
                    parts=list(dict.fromkeys(v.strip() for k in ('name','admin2','admin1','country') if isinstance(v:=row.get(k),str) and v.strip()))
                    if parts:items.append({'label':', '.join(parts)[:200],'lat':lat,'lon':lon})
                return {'items':items,'source':'Open-Meteo / GeoNames','message':'Chọn và xác nhận khu vực; chưa lưu vị trí.' if items else 'Không tìm thấy khu vực. Thử tên quận/thành phố hoặc nhập tọa độ thủ công.'}
            except Exception:
                raise HTTPException(502,'Không tra được khu vực. Kiểm tra Internet hoặc nhập tọa độ thủ công.') from None
        return await asyncio.to_thread(lookup)

    @staticmethod
    def valid(location):
        if not location:
            return False
        age = time()*1000-location['timestamp']
        return -60000 <= age <= (30*86400000 if location['source']=='manual' else 900000) and (
            location['source']=='manual' or location['accuracy'] is not None and location['accuracy']<=500)

    def snapshot(self):
        value = next((value for value in [self.device.get('phone'),self.device.get('browser'),self.manual] if self.valid(value)),None)
        return {'revision': self.revision, 'status': 'ready' if value else 'location_required',
                'phone_ready': self.valid(self.device.get('phone')), 'manual_ready': self.valid(self.manual),
                'current': value, 'has_saved':bool(self.device or self.manual), 'message': 'Vị trí dùng chung đã chọn' if value else 'Chọn hoặc cập nhật vị trí. Không suy vị trí từ IP/hotspot.'}

    def resolve(self, explicit=None, use_saved=True, source=None):
        if source:
            chosen = self.device.get('phone') if source == 'phone' else self.manual
            return chosen if self.valid(chosen) else None
        if explicit and (explicit.get('lat') is None)!=(explicit.get('lon') is None):raise HTTPException(422,'Cần nhập đủ vĩ độ và kinh độ.')
        if explicit and explicit.get('lat') is not None and explicit.get('lon') is not None:
            return {**explicit, 'source':'manual', 'timestamp':time()*1000, 'accuracy':None}
        return self.snapshot()['current'] if use_saved else None

    def update(self, payload, clear=False):
        request_id=payload['request_id'];fingerprint=json.dumps([payload,clear],sort_keys=True)
        if request_id in self.requests:
            if self.requests[request_id]!=fingerprint:raise HTTPException(409,'Mã yêu cầu vị trí đã dùng cho nội dung khác.')
            return
        if payload['expected_revision']!=self.revision:raise HTTPException(409,'Vị trí đã đổi trên thiết bị khác. Kiểm tra rồi thử lại.')
        value=None if clear else {k:payload[k] for k in ('lat','lon','accuracy','timestamp','source','label')}
        if value and not self.valid(value):raise HTTPException(422,'Vị trí quá cũ, nằm trong tương lai hoặc sai số trên 500 m. Hãy cập nhật hoặc chọn vị trí thủ công.')
        manual,device=self.manual,dict(self.device)
        if clear:manual=None;device={}
        elif value['source']=='manual':manual=value
        else:device[value['source']]=value
        with self.store.connect() as db:
            db.execute('UPDATE shared_location SET revision=?,manual=?,device=? WHERE id=1',
                (self.revision+1,json.dumps(manual) if manual else None,json.dumps(device) if device else None))
        self.manual,self.device=manual,device
        self.revision+=1
        if len(self.requests)>=128:self.requests.pop(next(iter(self.requests)))
        self.requests[request_id]=fingerprint
