"""One-shot DNS-SD lookup for Windows tooling; no credentials or AI backend."""
import ipaddress
import json
import threading
from zeroconf import IPVersion, ServiceBrowser, Zeroconf


def discover(timeout=3):
    origins = set()
    lock = threading.Lock()

    class Listener:
        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name, timeout=800)
            if not info or info.properties.get(b'app') != b'DAKT-Nc':
                return
            for address in info.parsed_addresses(IPVersion.V4Only):
                ip = ipaddress.ip_address(address)
                if ip.is_private and not ip.is_loopback and not ip.is_link_local and 0 < info.port < 65536:
                    with lock:
                        if len(origins) < 8:
                            origins.add(f'http://{address}:{info.port}')

        def update_service(self, *args):
            self.add_service(*args)

        def remove_service(self, *args):
            pass

    zc = Zeroconf(ip_version=IPVersion.V4Only)
    browser = None
    try:
        browser = ServiceBrowser(zc, '_deafy._tcp.local.', Listener())
        threading.Event().wait(timeout)
        with lock:
            return {'origins': sorted(origins)}
    finally:
        if browser:
            browser.cancel()
        zc.close()


if __name__ == '__main__':
    print(json.dumps(discover()))
