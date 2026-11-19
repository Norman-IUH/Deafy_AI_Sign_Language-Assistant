import asyncio
from io import BytesIO
import json
from urllib.parse import parse_qs

from thingspeak_logger import ThingSpeakLogger


def logger(monkeypatch):
    monkeypatch.setenv('THINGSPEAK_WRITE_API_KEY', 'test-secret')
    monkeypatch.setenv('THINGSPEAK_CHANNEL_ID', '3561048')
    return ThingSpeakLogger()


def test_telemetry_headers_fields_and_redaction(monkeypatch):
    telemetry = logger(monkeypatch)
    def response(request, timeout):
        assert request.full_url == 'https://api.thingspeak.com/update.json'
        assert request.get_header('Thingspeakapikey') == 'test-secret'
        data = parse_qs(request.data.decode())
        assert data['field1'] == ['1'] and 'field2' not in data and data['field3'] == ['ai']
        assert 'api_key' not in data and 'question' not in data
        return BytesIO(json.dumps({'channel_id': 3561048, 'entry_id': 12}).encode())
    monkeypatch.setattr('thingspeak_logger.urlopen', response)
    telemetry.observe('ai', {'light': True, 'fan': None}, True)
    assert telemetry.write(telemetry.pending) == 12
    assert 'test-secret' not in json.dumps(telemetry.status())


def test_coalesces_rate_limits_and_keeps_retry_separate(monkeypatch):
    async def scenario():
        telemetry = logger(monkeypatch)
        writes = []
        monkeypatch.setattr(telemetry, 'write', lambda data: writes.append(data) or 42)
        telemetry.observe('iot', {'light': None, 'fan': None}, True)
        telemetry.observe('ai', {'light': True, 'fan': False}, True)
        telemetry.tick()
        await telemetry.task
        assert len(writes) == 1 and writes[0]['field3'] == 'ai'
        assert telemetry.entry_id == 42
        telemetry.observe('iot', {'light': False, 'fan': False}, True)
        telemetry.tick()
        assert len(writes) == 1 and telemetry.pending['field3'] == 'iot'
        telemetry.next_attempt = 0
        def fail(data):
            raise OSError('test-secret')
        monkeypatch.setattr(telemetry, 'write', fail)
        telemetry.tick()
        await telemetry.task
        assert telemetry.pending and telemetry.error and 'test-secret' not in telemetry.error
        assert 'IoT local' in telemetry.error
    asyncio.run(scenario())
