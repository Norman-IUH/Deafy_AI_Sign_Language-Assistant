import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from server import create_app


def test_proxy_header_auth_keeps_unauthenticated_clients_out(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN', 'preview-test-only')
    monkeypatch.setattr('server.ROOT', tmp_path)
    with TestClient(create_app(tmp_path / 'preview.sqlite3')) as client:
        assert client.get('/api/state').status_code == 401
        assert client.post('/api/pi/speech', json={'request_id': 'unauthorized-tts', 'epoch': 'old', 'text': 'Xin chào'}).status_code == 401
        with client.websocket_connect('/ws', headers={'authorization': 'Bearer preview-test-only'}) as ws:
            ws.send_json({'token': ''})
            assert ws.receive_json()['type'] == 'state'
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={'authorization': 'Bearer wrong'}) as ws:
                ws.send_json({'token': ''})
                ws.receive_json()
