"""Bounded Open-Meteo lookup; values come from the API, never an LLM."""
import asyncio
from datetime import datetime
import json
import math
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo


class WeatherService:
    def __init__(self):
        self.cache={}

    def lookup(self, location):
        if not location:
            return {'status':'location_required','message':'LOCATION_REQUIRED · Chọn/cấp quyền vị trí trước khi xem thời tiết.','source':'Open-Meteo'}
        key=(round(location['lat'],3),round(location['lon'],3),location.get('label',''))
        cached=self.cache.get(key)
        if cached and monotonic()-cached[0]<300 and datetime.now(ZoneInfo(cached[1]['timezone'])).date().isoformat()==cached[1]['local_date']:
            return {**cached[1],'cached':True}
        query=urlencode({'latitude':location['lat'],'longitude':location['lon'],
            'current':'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code',
            'daily':'temperature_2m_max,temperature_2m_min,precipitation_probability_max','timezone':'auto','forecast_days':1})
        result={'status':'error','message':'Không lấy được thời tiết mới. Kiểm tra Internet rồi thử lại; không dùng dữ liệu cũ để đoán.', 'source':'Open-Meteo'}
        try:
            with urlopen(Request('https://api.open-meteo.com/v1/forecast?'+query,headers={'User-Agent':'SignAssist/1.0'}),timeout=8) as response:data=json.load(response)
            zone=ZoneInfo(data['timezone']);today=datetime.now(zone).date().isoformat()
            current=data.get('current',{});daily=data.get('daily',{})
            observed=datetime.fromisoformat(current['time']).replace(tzinfo=zone)
            if abs((datetime.now(zone)-observed).total_seconds())>7200:raise ValueError('stale current data')
            if daily.get('time') and daily['time'][0]!=today:raise ValueError('wrong local day')
            def number(value,low,high):return value if type(value) in (int,float) and math.isfinite(value) and low<=value<=high else None
            now={k:number(current.get(k),*bounds) for k,bounds in {'temperature_2m':(-100,70),'relative_humidity_2m':(0,100),'apparent_temperature':(-120,90),'precipitation':(0,1000),'weather_code':(0,99)}.items()}
            forecast={k:number((daily.get(k) or [None])[0],*bounds) for k,bounds in {'temperature_2m_max':(-100,70),'temperature_2m_min':(-100,70),'precipitation_probability_max':(0,100)}.items()}
            if now['temperature_2m'] is None:raise ValueError('missing temperature')
            unit=data.get('current_units',{})
            if unit.get('temperature_2m')!='°C' or unit.get('relative_humidity_2m') not in ('%',None) or unit.get('precipitation') not in ('mm',None):raise ValueError('unsupported units')
            pieces=[f'Thời tiết hôm nay tại {location.get("label") or "vị trí đã chọn"}. Nhiệt độ hiện tại {now["temperature_2m"]} độ C.']
            descriptions={0:'Trời quang',1:'Trời gần như quang',2:'Có mây rải rác',3:'Nhiều mây',45:'Có sương mù',48:'Có sương mù đóng băng',51:'Mưa phùn nhẹ',53:'Mưa phùn',55:'Mưa phùn mạnh',56:'Mưa phùn đóng băng',57:'Mưa phùn đóng băng mạnh',61:'Mưa nhẹ',63:'Có mưa',65:'Mưa mạnh',66:'Mưa đóng băng',67:'Mưa đóng băng mạnh',71:'Tuyết nhẹ',73:'Có tuyết',75:'Tuyết mạnh',77:'Hạt tuyết',80:'Mưa rào nhẹ',81:'Mưa rào',82:'Mưa rào mạnh',85:'Tuyết rào',86:'Tuyết rào mạnh',95:'Có giông',96:'Giông kèm mưa đá',99:'Giông kèm mưa đá mạnh'}
            if now['weather_code'] in descriptions:pieces.append(descriptions[now['weather_code']]+'.')
            for field,label,suffix in [('relative_humidity_2m','Độ ẩm hiện tại','phần trăm'),('apparent_temperature','Nhiệt độ cảm nhận','độ C'),('precipitation','Lượng giáng thủy hiện tại','mi li mét')]:
                if now[field] is not None:pieces.append(f'{label} {now[field]} {suffix}.')
            if forecast['precipitation_probability_max'] is not None:pieces.append(f'Khả năng có mưa cao nhất dự báo trong ngày {forecast["precipitation_probability_max"]} phần trăm.')
            if forecast['temperature_2m_min'] is not None and forecast['temperature_2m_max'] is not None:pieces.append(f'Nhiệt độ dự báo trong ngày từ {forecast["temperature_2m_min"]} đến {forecast["temperature_2m_max"]} độ C.')
            result={'status':'ok','source':'Open-Meteo','timezone':data['timezone'],'local_date':today,'updated_at':current['time'],
                    'observed_at': observed.isoformat(), 'label': location.get('label') or 'Vị trí đã chia sẻ',
                    'condition': descriptions.get(now['weather_code']),
                    'current':now,'daily':forecast,'message':' '.join(pieces),'cached':False}
            spoken = [f'Hiện tại {now["temperature_2m"]} độ C.']
            if result['condition']: spoken.append(result['condition']+'.')
            if forecast['precipitation_probability_max'] is not None:
                spoken.append(f'Khả năng mưa hôm nay {forecast["precipitation_probability_max"]} phần trăm.')
            result['speech_text'] = ' '.join(spoken)
            if len(self.cache)>=8:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(monotonic(),result)
        except Exception:pass  # Do not expose URLs containing precise coordinates or provider responses.
        return result

    async def get(self,location):return await asyncio.to_thread(self.lookup,location)
