"""Bounded Geoapify requests. Credentials and query URLs stay in this module."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from random import uniform
from threading import Lock
from time import monotonic, sleep, time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from osm_places import normalized

FOOD = 'catering.restaurant,catering.fast_food,catering.food_court'
CATEGORIES = {'quán cơm': FOOD, 'quán cơm tấm': FOOD, 'quán ăn': FOOD,
              'quán cà phê': 'catering.cafe', 'nhà thuốc': 'healthcare.pharmacy',
              'bệnh viện': 'healthcare.hospital', 'ATM': 'service.financial.atm'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


open_places = build_opener(NoRedirect()).open


class GeoapifyPlaces:
    def __init__(self):
        self.cache = {}
        self.lock = Lock()
        self.blocked_until = 0
        self.blocked_result = None

    def search(self, query, location, api_key):
        from assistant import distance_m

        def fail(code, message):
            return {**base, 'status': 'error', 'error_code': code, 'message': message}

        base = {'query': query, 'source': 'Geoapify', 'items': [],
                'searched_at': datetime.now(timezone.utc).isoformat(), 'cached': False}
        if not api_key:
            return fail('NOT_CONFIGURED', 'Geoapify chưa có khóa Free trên Pi.')
        if not isinstance(query,str) or not query.strip() or len(query)>200:
            return fail('UNSUPPORTED_QUERY', 'Nhập tên địa điểm hoặc địa chỉ ngắn gọn.')
        lat, lon = location['lat'], location['lon']
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            return fail('LOCATION_REQUIRED', 'Hãy chia sẻ lại GPS từ iPhone.')
        cache_key = (query, lat, lon)
        with self.lock:
            cached = self.cache.get(cache_key)
            if cached and monotonic() - cached[0] < 300:
                return {**cached[1], 'cached': True}
            if monotonic() < self.blocked_until:
                return {**base, **self.blocked_result}
            try:
                named = query not in CATEGORIES
                for radius in ((3000,) if named else (1500,3000)):
                    params = urlencode({'categories': CATEGORIES.get(query,''), 'filter': f'circle:{lon},{lat},{radius}',
                                        'bias': f'proximity:{lon},{lat}', 'lang': 'vi', 'limit': 20, 'apiKey': api_key})
                    if named:
                        params = urlencode({'text':query,'bias':f'proximity:{lon},{lat}','lang':'vi','limit':5,'apiKey':api_key})
                        endpoint = 'https://api.geoapify.com/v1/geocode/search?'
                    else:
                        endpoint = 'https://api.geoapify.com/v2/places?'
                    data = self.fetch(Request(endpoint + params))
                    items = []
                    for feature in data['features']:
                        p = feature['properties']
                        a, b = p.get('lat'), p.get('lon')
                        if not all(type(v) in (int, float) and math.isfinite(v) for v in (a, b)):
                            continue
                        if not -90 <= a <= 90 or not -180 <= b <= 180:
                            continue
                        distance = distance_m((lat, lon), (a, b))
                        if not named and distance > radius:
                            continue
                        name = (p.get('name') or (p.get('address_line1') if named else '') or '').strip()[:160]
                        if not name:
                            continue
                        address = (p.get('formatted') or '').strip()[:300]
                        if address.startswith(name + ','):
                            address = address[len(name) + 1:].strip()
                        if address == name:
                            address = ''
                        complete = bool(p.get('street') and p.get('housenumber'))
                        if not complete:
                            address = f'{address} · Thiếu địa chỉ chi tiết' if address else 'Thiếu địa chỉ chi tiết'
                        relevant = query not in ('quán cơm', 'quán cơm tấm') or normalized(query)[4:] in normalized(name)
                        items.append((p.get('place_id'), {'name': name, 'address': address,
                                     'address_complete': complete, 'distance_m': distance}, relevant, a, b))
                    ranked = sorted(items, key=lambda row: (not row[2], not row[1]['address_complete'], row[1]['distance_m']))
                    results, identities, positions = [], set(), []
                    for identifier, item, _, a, b in ranked:
                        name_key = normalized(item['name'])
                        if (identifier and identifier in identities) or any(
                                name_key == n and distance_m((a, b), (c, d)) <= 30 for n, c, d in positions):
                            continue
                        identities.add(identifier)
                        positions.append((name_key, a, b))
                        results.append(item)
                        if len(results) == (1 if named else 3):
                            break
                    if results:
                        break
                result = {**base, 'items': results, 'status': 'ok' if results else 'empty',
                          'message': ('Kết quả địa chỉ theo tên; không khẳng định gần nhất.' if named else f'Tìm trong bán kính {radius:,} m.'.replace(',', '.')) if results
                          else 'Không tìm thấy địa điểm hoặc địa chỉ phù hợp.'}
                if not results:
                    result['error_code'] = 'ZERO_RESULTS'
                self.cache[cache_key] = (monotonic(), result)
                if len(self.cache) > 24:
                    self.cache.pop(next(iter(self.cache)))
                return result
            except HTTPError as issue:
                status = issue.code
                if status == 429 or status >= 500:
                    code, message = ('QUOTA_EXCEEDED', 'Geoapify đã hết hạn mức hoặc đang giới hạn lượt.') if status == 429 else (
                        'UNAVAILABLE', 'Geoapify tạm thời không phản hồi.')
                    self.blocked_result = {'status': 'error', 'error_code': code, 'message': message}
                    self.blocked_until = monotonic() + self.retry_delay(issue, 60)
                    issue.close()
                    return fail(code, message)
                issue.close()
                return fail('API_ERROR', 'Geoapify từ chối yêu cầu. Kiểm tra khóa và quyền của project.')
            except (URLError, TimeoutError, OSError):
                self.blocked_until = monotonic() + 30
                self.blocked_result = {'status': 'error', 'error_code': 'NETWORK_ERROR',
                                       'message': 'Không kết nối được Geoapify trong thời gian chờ.'}
                return {**base, **self.blocked_result}
            except (ValueError, TypeError, KeyError, AttributeError):
                return fail('INVALID_RESPONSE', 'Geoapify trả dữ liệu không hợp lệ.')

    @staticmethod
    def retry_delay(issue, default):
        value = issue.headers.get('Retry-After', '') if issue.headers else ''
        try:
            seconds = int(value) if value.isdecimal() else parsedate_to_datetime(value).timestamp() - time()
            return max(default, seconds)
        except (ValueError, TypeError, OverflowError):
            return default

    def fetch(self, request):
        for attempt in range(2):
            delay = 0.5 * 2 ** attempt + uniform(0, 0.25)
            try:
                with open_places(request, timeout=4) as response:
                    raw = response.read(500001)
                if len(raw) > 500000:
                    raise ValueError('response too large')
                return json.loads(raw)
            except HTTPError as issue:
                if attempt or issue.code < 500 or self.retry_delay(issue, 0) > 1:
                    raise
                delay = max(delay, self.retry_delay(issue, 0))
                issue.close()
            except (URLError, TimeoutError):
                if attempt:
                    raise
            sleep(delay)
