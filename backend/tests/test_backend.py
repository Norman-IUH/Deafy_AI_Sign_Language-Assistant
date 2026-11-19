from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from server import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv('DAKT_API_TOKEN', raising=False)
    monkeypatch.delenv('DAKT_ALLOW_DELETE', raising=False)
    monkeypatch.setattr('server.ROOT', tmp_path)
    return create_app(tmp_path / 'test.sqlite3')


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def command(client, action='set', text='Xin chào', revision=0, request_id='request-0001'):
    return client.post('/api/commands', json={'action': action, 'text': text,
                       'expected_revision': revision, 'request_id': request_id})


def test_health_without_model(client):
    health = client.get('/api/health').json()
    assert health['ready'] is True
    assert health['ai']['ready'] is False
    assert health['ai']['status'] == 'missing'
    assert client.get('/api/state').json()['recognition']['status'] == 'unavailable'
    assert client.get('/api/camera/frame').status_code == 503
    assert client.get('/api/devices').json()['configured'] is False


def test_confirmed_sign_snapshot_has_stable_id_without_model(app):
    import time
    with TestClient(app) as client:
        camera = app.state.camera
        camera.pending.append({'id': 'test-confirmed', 'label': 'xin_chao', 'text': 'Xin chào'})
        camera.serial += 1
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshot = client.get('/api/state').json()
            if snapshot['confirmed_sign']:
                break
            time.sleep(.03)
        assert snapshot['confirmed_sign']['id'] == 'test-confirmed'
        assert snapshot['confirmed_sign']['speakable'] is True
        assert snapshot['sentence'] == ''
        assert snapshot['pi']['caption']['text'] == 'Xin chào'
        assert client.get('/api/state').json()['confirmed_sign'] == snapshot['confirmed_sign']


def test_idempotent_command_and_stale_revision(client):
    first = command(client).json()
    repeat = command(client).json()
    assert first['revision'] == repeat['revision'] == 1
    assert command(client, text='Nội dung khác').status_code == 409
    assert command(client, request_id='request-0002').status_code == 409
    assert client.get('/api/state').json()['sentence'] == 'Xin chào'


def test_edit_operations(client):
    assert command(client, text='a').status_code == 200
    assert command(client, 'space', revision=1, request_id='request-0002').json()['state']['sentence'] == 'a '
    assert command(client, 'space', revision=2, request_id='request-0003').json()['state']['sentence'] == 'a '
    assert command(client, 'backspace', revision=3, request_id='request-0004').json()['state']['sentence'] == 'a'
    assert command(client, 'clear', revision=4, request_id='request-0005').json()['state']['sentence'] == ''
    assert command(client, 'backspace', revision=5, request_id='request-0006').json()['state']['sentence'] == ''


def test_history_search_detail_and_delete(client):
    payload = {'request_id': 'message-0001', 'kind': 'conversation',
               'text': 'Xin chào <script>alert(1)</script> 100%', 'transcript': 'Bạn khỏe không?'}
    result = client.post('/api/history', json=payload)
    assert result.status_code == 200
    assert client.post('/api/history', json=payload).json()['id'] == result.json()['id']
    assert client.get('/api/history').json()['total'] == 1
    assert client.get('/api/history', params={'q': '100%'}).json()['total'] == 1
    assert client.get('/api/history', params={'q': '%not-present'}).json()['total'] == 0
    assert client.get('/api/history', params={'q': 'khỏe'}).json()['total'] == 1
    assert client.get('/api/history', params={'q': 'KHỎE'}).json()['total'] == 1
    item_id = result.json()['id']
    assert client.get(f'/api/history/{item_id}').json()['transcript'] == payload['transcript']
    assert client.delete(f'/api/history/{item_id}').status_code == 200
    assert client.delete(f'/api/history/{item_id}').status_code == 200
    assert client.get(f'/api/history/{item_id}').status_code == 404


def test_validation(client):
    assert command(client, text='x' * 2001).status_code == 422
    assert client.post('/api/history', json={'request_id': 'empty-001', 'text': '   '}).status_code == 422
    assert client.get('/api/history?limit=999').status_code == 422
    assert client.get('/api/history?offset=-1').status_code == 422
    assert client.post('/api/commands', json={'action': 'execute'}).status_code == 422


def test_speech_synchronizes(client):
    result = client.post('/api/history', json={'request_id': 'speech-001', 'kind': 'speech', 'text': 'Tôi đang nghe'}).json()
    assert result['state']['transcript'] == 'Tôi đang nghe'
    assert client.get('/api/history').json()['items'][0]['kind'] == 'speech'
    # Captions/history updates must not invalidate a sentence being edited.
    assert command(client).status_code == 200


def test_persistence_and_retry_after_restart(tmp_path):
    path = tmp_path / 'persist.sqlite3'
    with TestClient(create_app(path)) as first:
        assert command(first).status_code == 200
    with TestClient(create_app(path)) as second:
        assert second.get('/api/state').json()['sentence'] == 'Xin chào'
        assert command(second).json()['revision'] == 1


def test_two_websocket_clients_receive_same_state(client):
    with client.websocket_connect('/ws') as web, client.websocket_connect('/ws') as mobile:
        web.send_json({'token': ''}); mobile.send_json({'token': ''})
        assert web.receive_json()['type'] == mobile.receive_json()['type'] == 'state'
        command(client)
        for ws in (web, mobile):
            for _ in range(5):
                packet = ws.receive_json()
                if packet['state']['revision'] == 1:
                    assert packet['state']['sentence'] == 'Xin chào'
                    break
            else:
                pytest.fail('State did not reach both screens')


def test_token_origin_and_delete_policy(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN', 'test-token')
    monkeypatch.setenv('DAKT_ALLOW_DELETE', 'false')
    with TestClient(create_app(tmp_path / 'auth.sqlite3')) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/state').status_code == 401
        headers = {'Authorization': 'Bearer test-token'}
        assert client.get('/api/state', headers=headers).status_code == 200
        assert client.delete('/api/history/1', headers=headers).status_code == 403
        with client.websocket_connect('/ws') as ws:
            ws.send_json({'token': 'wrong'})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={'origin': 'https://untrusted.invalid'}):
                pass


def test_concurrent_edits_have_one_winner(app):
    def mutate(index):
        try:
            app.state.store.mutate('command', {'request_id': f'parallel-{index}', 'expected_revision': 0,
                                             'action': 'append', 'text': str(index)})
            return 200
        except Exception as exc:
            return getattr(exc, 'status_code', 500)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(mutate, (1, 2))) == [200, 409]
    assert app.state.store.snapshot()['revision'] == 1


def test_composition_keeps_words_and_accents_explicit():
    from text_composition import compose_sign
    assert compose_sign('a', 'b', 'b') == 'ab'
    assert compose_sign('Xin chào', 'dong_y', 'Đồng ý') == 'Xin chào Đồng ý'
    assert compose_sign('a', 'dau_sac', 'Dấu sắc') == 'a'
    assert compose_sign('a', 'blank', '') == 'a'


def test_camera_missing_dependency_is_reported(tmp_path, monkeypatch):
    import sys
    from recognition_service import CameraService
    monkeypatch.setitem(sys.modules, 'cv2', None)
    service = CameraService(tmp_path)
    service.start()
    service.thread.join(timeout=2)
    assert not service.thread.is_alive()
    assert service.status()['running'] is False
    assert 'requirements-camera.txt' in service.status()['error']
    assert service.frame() is None
    service.stop()


def test_checkpoint_presence_is_not_model_readiness(tmp_path):
    from recognition_service import CameraService
    (tmp_path / 'data').mkdir()
    for name in ('hand_pose.pt', 'gru_best.pt'):
        (tmp_path / 'data' / name).write_bytes(b'not a model')
    service = CameraService(tmp_path)
    assert service.ai_status()['model_present'] is True
    assert service.ai_status()['ready'] is False


def test_existing_state_is_migrated_without_losing_text(tmp_path):
    import sqlite3
    from server import Store
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE state(id INTEGER PRIMARY KEY, revision INTEGER, sentence TEXT, transcript TEXT)')
        db.execute("INSERT INTO state VALUES(1,8,'Câu đã lưu','Lời nói cũ')")
    state = Store(path).snapshot()
    assert state['sentence'] == 'Câu đã lưu'
    assert state['transcript'] == 'Lời nói cũ'
    assert state['sentence_revision'] == 8


def test_both_frontend_origins_are_allowed(client):
    for origin in ('http://localhost:5173', 'http://localhost:5174', 'http://127.0.0.1:5174'):
        response = client.options('/api/state', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'GET'})
        assert response.headers['access-control-allow-origin'] == origin
    denied = client.options('/api/state', headers={
        'Origin': 'https://untrusted.invalid', 'Access-Control-Request-Method': 'GET'})
    assert 'access-control-allow-origin' not in denied.headers
