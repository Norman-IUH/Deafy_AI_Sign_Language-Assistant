"""Opt-in real broker test; the ESP is a software simulator, no relays are touched."""
import asyncio
from io import BytesIO
import json
import os
import wave

import pytest

from server import Store
from pi_modes import PiModes


@pytest.mark.skipif(not os.getenv('DAKT_TEST_MQTT_PORT'), reason='Set DAKT_TEST_MQTT_PORT for a loopback test broker')
def test_real_broker_iot_and_speech(monkeypatch, tmp_path):
    import paho.mqtt.client as mqtt
    monkeypatch.setenv('DAKT_MQTT_HOST', '127.0.0.1')
    monkeypatch.setenv('DAKT_MQTT_PORT', os.environ['DAKT_TEST_MQTT_PORT'])
    monkeypatch.setenv('DAKT_MQTT_TOPIC', 'signassist-test/esp32')
    monkeypatch.setenv('DAKT_AI_PROVIDER', 'mock')
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://192.168.1.164:8001')
    for key in ('DAKT_MQTT_USER', 'DAKT_MQTT_PASSWORD', 'DAKT_MQTT_TLS'):
        monkeypatch.delenv(key, raising=False)
    topic = 'signassist-test/esp32'
    esp = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    session = {}
    commands = []

    def on_connect(client, userdata, flags, reason, properties):
        client.subscribe(topic + '/#', qos=1)
        client.publish(topic + '/status', json.dumps({'kind': 'hello'}))

    def on_message(client, userdata, message):
        data = json.loads(message.payload)
        kind = message.topic.rsplit('/', 1)[1]
        if kind == 'mode':
            session.update(data)
        elif kind in ('command', 'speech'):
            if data['epoch'] != session.get('epoch') or data['mode'] != session.get('mode'):
                return
            commands.append((kind, data))
            for state in (('ACK', 'DONE') if kind == 'command' else ('ACK', 'PLAYING', 'DONE')):
                packet = {**data, 'kind': 'iot' if kind == 'command' else 'speech', 'status': state}
                client.publish(topic + '/status', json.dumps(packet), qos=1, retain=False)

    esp.on_connect, esp.on_message = on_connect, on_message
    esp.connect('127.0.0.1', int(os.environ['DAKT_TEST_MQTT_PORT']))
    esp.loop_start()

    async def until(predicate):
        for _ in range(250):
            if predicate():
                return
            await asyncio.sleep(.02)
        raise AssertionError('Broker/ESP simulator timed out')

    async def scenario():
        pi = PiModes(Store(tmp_path / 'mqtt.sqlite3'))
        pi.mqtt.start(pi.on_status)
        try:
            await until(lambda: pi.mqtt.connected)
            pi.set_mode('iot', pi.epoch, 'broker-mode-iot')
            await until(lambda: session.get('epoch') == pi.epoch)
            pi.control(pi.epoch, 'broker-light-on', 'light', True)
            await until(lambda: pi.iot['status'] == 'DONE')
            assert pi.devices['light'] is True
            pi.set_mode('ai', pi.epoch, 'broker-mode-ai')
            await until(lambda: session.get('epoch') == pi.epoch)
            audio = BytesIO()
            with wave.open(audio, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050); wav.writeframes(b'\0\0' * 100)
            pi.tts.ready = True
            monkeypatch.setattr(pi.tts, 'synthesize_cloud', lambda text, voice, speed: audio.getvalue())
            pi.ask(dict(request_id='broker-question', epoch=pi.epoch, text='Bật đèn?'))
            await pi.task
            await until(lambda: pi.speech['status'] == 'DONE')
            assert [kind for kind, _ in commands] == ['command', 'speech']
            assert 'MOCK' in pi.ai['answer']
        finally:
            await pi.stop()

    try:
        asyncio.run(scenario())
    finally:
        esp.disconnect()
        esp.loop_stop()
