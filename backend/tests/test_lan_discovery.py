import hashlib
import hmac
import pytest
from fastapi.testclient import TestClient
import lan_discovery
from server import create_app


def test_origin_tracks_dhcp_and_proof_is_bound_to_current_origin(monkeypatch):
    monkeypatch.setenv('DAKT_DISCOVERY_ENABLED', '1')
    monkeypatch.setenv('DAKT_API_TOKEN', 'paired-api-secret')
    monkeypatch.setenv('DAKT_MQTT_PASSWORD', 'paired-mqtt-secret')
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL', 'http://192.168.137.20:8001')
    monkeypatch.setattr(lan_discovery, 'lan_ipv4', lambda: '192.168.137.122')
    nonce = 'a' * 32
    first = lan_discovery.discovery_proof(nonce, 'api')
    assert first['origin'] == 'http://192.168.137.122:8001'
    message = f'deafy-discovery-v1\napi\n{nonce}\n{first["origin"]}\n1883'
    assert first['proof'] == hmac.new(b'paired-api-secret', message.encode(), hashlib.sha256).hexdigest()
    assert lan_discovery.discovery_proof(nonce, 'mqtt')['proof'] != first['proof']
    monkeypatch.setattr(lan_discovery, 'lan_ipv4', lambda: '192.168.137.125')
    assert lan_discovery.audio_origin() == 'http://192.168.137.125:8001'
    assert lan_discovery.discovery_proof(nonce, 'api')['proof'] != first['proof']
    assert 'paired-api-secret' not in str(first)


@pytest.mark.parametrize('nonce,kind', [('bad', 'api'), ('b'*32, 'admin'), ('B'*32, 'mqtt')])
def test_bad_challenge_rejected(nonce, kind):
    with pytest.raises(ValueError):
        lan_discovery.discovery_proof(nonce, kind)


def test_proof_route_never_returns_credentials_and_auth_still_required(monkeypatch, tmp_path):
    monkeypatch.setenv('DAKT_DISCOVERY_ENABLED', '1')
    monkeypatch.setenv('DAKT_API_TOKEN', 'paired-api-secret')
    monkeypatch.setattr(lan_discovery, 'lan_ipv4', lambda: '192.168.137.122')
    client = TestClient(create_app(tmp_path / 'db.sqlite3'))
    response = client.get('/api/discovery', params={'challenge': 'b'*32})
    assert response.status_code == 200
    assert set(response.json()) == {'service', 'origin', 'mqtt_port', 'proof'}
    assert 'paired-api-secret' not in response.text
    assert client.get('/api/state').status_code == 401
    assert client.get('/api/discovery', params={'challenge': 'bad'}).status_code == 400
