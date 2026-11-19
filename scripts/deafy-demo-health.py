"""Read-only demo status. No coordinates, tokens, or external billable calls."""
import json
from urllib.request import urlopen


def get(port, path):
    with urlopen(f'http://127.0.0.1:{port}{path}', timeout=4) as response:
        return json.load(response)


def status(label, value, detail=''):
    print(f'{"PASS" if value else "BLOCKED"} · {label}' + (f' · {detail}' if detail else ''))


def main():
    try:
        status('Backend + frontend', get(5173, '/api/health').get('ready'))
        state = get(5173, '/api/state')
    except (OSError, ValueError):
        status('Backend + frontend', False, 'Bấm Khởi động Deafy trên Desktop')
        return
    pi = state['pi']
    status('Camera có hình', state['camera']['has_frame'])
    model = state['ai'].get('model') or {}
    status('Model 2', state['ai']['ready'] and model.get('num_classes') == 22, str(model.get('name', '')))
    status('GPS iPhone', pi['location'].get('phone_ready'), 'Chia sẻ lại từ iPhone nếu hết hạn')
    status('Pi → broker MQTT', pi['mqtt']['connected'])
    print('ESP32 · theo dõi ACK/PLAYING/DONE sau khi bấm nghe thử')
    print(f'Giọng đã lưu · {pi["speaker"]["voice"]}')
    try:
        cit = get(18001, '/health')
        status('Laptop CIT CUDA', cit.get('device') == 'cuda', str(cit.get('engine', '')))
    except (OSError, ValueError):
        status('Laptop CIT', False, 'Mở CIT và START_DEAFY_DEMO.bat trên laptop')


if __name__ == '__main__':
    main()
