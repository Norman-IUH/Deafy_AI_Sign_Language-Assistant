"""Advertise the existing Pi server; discovery never carries application credentials."""
import hashlib
import hmac
import ipaddress
import logging
import os
import re
import socket
import threading


def lan_ipv4():
    # A UDP route lookup sends no packet and follows Wi-Fi/DHCP changes.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(('224.0.0.251', 5353))
        address = sock.getsockname()[0]
    parsed = ipaddress.ip_address(address)
    if parsed.is_loopback or parsed.is_unspecified or parsed.is_link_local:
        raise OSError('Pi chưa có địa chỉ IPv4 LAN.')
    return address


def audio_origin():
    if os.getenv('DAKT_DISCOVERY_ENABLED') == '1':
        return f'http://{lan_ipv4()}:{int(os.getenv("DAKT_HTTP_PORT", "8001"))}'
    return os.getenv('DAKT_AUDIO_BASE_URL', '').rstrip('/')


def discovery_proof(challenge, kind):
    if not re.fullmatch(r'[a-f0-9]{32}', challenge) or kind not in ('api', 'mqtt'):
        raise ValueError('Tham số khám phá không hợp lệ.')
    key = os.getenv('DAKT_API_TOKEN' if kind == 'api' else 'DAKT_MQTT_PASSWORD', '')
    if not key:
        raise ValueError('Chưa cấu hình mã ghép nối cho dịch vụ này.')
    origin = audio_origin()
    port = int(os.getenv('DAKT_MQTT_PORT', '1883'))
    message = f'deafy-discovery-v1\n{kind}\n{challenge}\n{origin}\n{port}'
    return {'service': 'DAKT-Nc', 'origin': origin, 'mqtt_port': port,
            'proof': hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()}


class LANDiscovery:
    def __init__(self):
        self.enabled = os.getenv('DAKT_DISCOVERY_ENABLED') == '1'
        self.address = ''
        self.error = ''
        self.stop_event = threading.Event()
        self.thread = None

    def status(self):
        return {'enabled': self.enabled, 'address': self.address, 'error': self.error}

    def start(self):
        if self.enabled and not self.thread:
            self.thread = threading.Thread(target=self.run, name='deafy-mdns', daemon=True)
            self.thread.start()

    def run(self):
        zc = info = None
        registered = False
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
            while not self.stop_event.is_set():
                try:
                    address = lan_ipv4()
                    if address != self.address or zc is None:
                        if zc:
                            try:
                                if registered:
                                    zc.unregister_service(info)
                            finally:
                                zc.close()
                                zc = None
                                registered = False
                        zc = Zeroconf(interfaces=[address], ip_version=IPVersion.V4Only)
                        info = ServiceInfo('_deafy._tcp.local.', 'Deafy SignAssist._deafy._tcp.local.',
                            addresses=[socket.inet_aton(address)],
                            port=int(os.getenv('DAKT_HTTP_PORT', '8001')),
                            properties={'app': 'DAKT-Nc', 'mqtt': os.getenv('DAKT_MQTT_PORT', '1883')},
                            server='deafy-service.local.')
                        zc.register_service(info, allow_name_change=True)
                        registered = True
                        self.address = address
                    self.error = ''
                except Exception:
                    self.address = ''
                    self.error = 'Chưa quảng bá được Pi trên LAN; sẽ tự thử lại.'
                    logging.getLogger(__name__).warning(self.error)
                self.stop_event.wait(3)
        except ImportError:
            self.error = 'Thiếu zeroconf. Cài requirements-iot.txt để tự tìm Pi.'
        finally:
            if zc:
                try:
                    if registered:
                        zc.unregister_service(info)
                finally:
                    zc.close()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=8)
