"""Optional LAN transport; all application state stays on the asyncio thread."""
import asyncio
import json
import os


class MQTTBridge:
    def __init__(self):
        self.host = os.getenv('DAKT_MQTT_HOST', '')
        self.topic = os.getenv('DAKT_MQTT_TOPIC', 'signassist/esp32')
        self.connected = False
        self.error = 'Chưa cấu hình MQTT/ESP32.'
        self.client = None

    def start(self, on_status):
        if not self.host:
            return
        try:
            import paho.mqtt.client as mqtt
            loop = asyncio.get_running_loop()
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                      client_id=os.getenv('DAKT_MQTT_CLIENT_ID', ''))
            user = os.getenv('DAKT_MQTT_USER')
            if user:
                self.client.username_pw_set(user, os.getenv('DAKT_MQTT_PASSWORD', ''))
            if os.getenv('DAKT_MQTT_TLS') == '1':
                self.client.tls_set()

            def connected(client, userdata, flags, reason, properties):
                self.connected = reason == 0
                self.error = '' if self.connected else 'Broker từ chối kết nối MQTT.'
                if self.connected:
                    client.subscribe(self.topic + '/status', qos=1)

            def disconnected(client, userdata, flags, reason, properties):
                self.connected = False
                self.error = 'Mất kết nối MQTT. Kiểm tra broker và Wi-Fi.'

            def message(client, userdata, packet):
                if packet.retain or len(packet.payload) > 2048:
                    return
                try:
                    data = json.loads(packet.payload)
                    if isinstance(data, dict):
                        loop.call_soon_threadsafe(on_status, data)
                except (ValueError, UnicodeError, RuntimeError):
                    pass

            self.client.on_connect = connected
            self.client.on_disconnect = disconnected
            self.client.on_message = message
            self.client.max_queued_messages_set(1)
            self.client.reconnect_delay_set(1, 15)
            self.client.connect_async(self.host, int(os.getenv('DAKT_MQTT_PORT', '1883')), 30)
            self.client.loop_start()
        except (ImportError, ValueError, OSError):
            self.error = 'Không khởi động được MQTT. Kiểm tra requirements-iot.txt và cấu hình broker.'

    def publish(self, kind, payload):
        if kind not in ('mode', 'speech') or (kind == 'mode' and payload.get('mode') != 'ai'):
            raise RuntimeError('Điều khiển relay đã bị vô hiệu hóa. ESP32 chỉ phát loa.')
        if not self.client or not self.connected:
            raise RuntimeError(self.error)
        result = self.client.publish(self.topic + '/' + kind, json.dumps(payload), qos=1, retain=False)
        if result.rc != 0:
            raise RuntimeError('Không gửi được MQTT. Lệnh không được tự động gửi lại.')

    def stop(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
