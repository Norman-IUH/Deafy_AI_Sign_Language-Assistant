"""Rate-limited, write-only telemetry. Never read cloud fields as device commands."""
import asyncio
import json
import os
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ThingSpeakLogger:
    def __init__(self):
        self.key = os.getenv('THINGSPEAK_WRITE_API_KEY', '')
        self.channel = os.getenv('THINGSPEAK_CHANNEL_ID', '')
        self.enabled = bool(self.key and self.channel.isdigit())
        self.error = ''
        self.entry_id = None
        self.last_seen = None
        self.pending = None
        self.next_attempt = 0
        self.task = None

    def status(self):
        return {'enabled': self.enabled, 'channel_id': self.channel if self.enabled else None,
                'last_entry_id': self.entry_id, 'error': self.error}

    def observe(self, mode, devices, connected):
        if not self.enabled:
            return
        data = {'field3': mode, 'status': json.dumps({'mqtt': connected, **devices}, separators=(',', ':'))}
        for field, device in (('field1', 'light'), ('field2', 'fan')):
            if type(devices[device]) is bool:
                data[field] = int(devices[device])
        if data != self.last_seen:
            self.last_seen = data
            # Coalesce rapid ACK/mode events into the newest status, not an unbounded queue.
            self.pending = data

    def tick(self):
        if not self.enabled or not self.pending or monotonic() < self.next_attempt:
            return
        if self.task and not self.task.done():
            return
        data, self.pending = self.pending, None
        self.next_attempt = monotonic() + 16
        self.task = asyncio.create_task(self.send(data))

    def write(self, data):
        request = Request('https://api.thingspeak.com/update.json', data=urlencode(data).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded',
                                   'THINGSPEAKAPIKEY': self.key}, method='POST')
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
        if not isinstance(result, dict) or str(result.get('channel_id')) != self.channel or not result.get('entry_id'):
            raise ValueError('ThingSpeak rejected the telemetry update')
        return result['entry_id']

    async def send(self, data):
        try:
            self.entry_id = await asyncio.to_thread(self.write, data)
            self.error = ''
        except asyncio.CancelledError:
            return
        except Exception:
            self.error = 'Chưa ghi được ThingSpeak. Kiểm tra Internet/key/hạn mức; IoT local vẫn hoạt động.'
            if self.pending is None:
                self.pending = data

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
