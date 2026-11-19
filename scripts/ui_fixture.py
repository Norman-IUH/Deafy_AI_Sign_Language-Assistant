"""Disposable UI test server on loopback :8002. Never uses production credentials/data."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

if __name__ == '__main__':
    for key in list(os.environ):
        if key.startswith(('DAKT_', 'THINGSPEAK_', 'GEMINI_','GROQ_','GOOGLE_')):
            del os.environ[key]
    os.environ['DAKT_AI_PROVIDER'] = 'mock'
    import uvicorn
    from fastapi import HTTPException

    with TemporaryDirectory(prefix='deafy-ui-') as folder:
        os.environ['DAKT_DB']=str(Path(folder)/'import-only.sqlite3')
        from server import create_app
        app = create_app(Path(folder) / 'fixture.sqlite3')
        async def fixture_weather(location):
            if not location:return {'status':'location_required','message':'LOCATION_REQUIRED · DỮ LIỆU KIỂM THỬ','source':'FIXTURE ONLY'}
            return {'status':'ok','message':'DỮ LIỆU KIỂM THỬ · Nhiệt độ hiện tại 28 độ C.','source':'FIXTURE ONLY','current':{'temperature_2m':28},'daily':{}}
        app.state.pi.weather.get=fixture_weather
        import pi_modes
        async def fixture_places(*args):
            return {'status':'ok','source':'© OpenStreetMap contributors · FIXTURE ONLY','cached':True,'stale':True,
                    'searched_at':'2026-11-05T12:00:00+00:00','message':'DỮ LIỆU KIỂM THỬ lưu trước, không phải địa điểm thật.',
                    'items':[{'name':'TEST Quán cơm','address':'TEST số 12, đường kiểm thử'},
                             {'name':'TEST Quán ăn','address':'Địa chỉ chưa đầy đủ trong OSM'}]}
        pi_modes.search_places=fixture_places

        @app.post('/test/microphone')
        async def microphone(body: dict):
            if body.get('status') not in ('idle', 'recording', 'done', 'error'):
                raise HTTPException(422, 'Invalid fixture status')
            mic = app.state.microphone
            mic.state.update(status=body['status'], text=str(body.get('text', ''))[:2000],
                             session=str(body.get('session', 'fixture')), source='WebCamera · USB (fixture)', error='')
            mic.version += 1
            return {'ok': True}

        uvicorn.run(app, host='127.0.0.1', port=8002, log_level='warning')
