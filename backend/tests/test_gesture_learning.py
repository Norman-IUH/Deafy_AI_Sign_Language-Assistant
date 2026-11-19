import base64
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np

from server import create_app


def test_camera_feedback_corrects_label_and_exports_only_reviewed_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN', 'test-learning')
    monkeypatch.setattr('server.ROOT', tmp_path)
    app = create_app(tmp_path / 'learning.sqlite3')
    auth = {'Authorization': 'Bearer test-learning'}
    camera = app.state.camera
    raw = np.full((30, 126), .25, dtype='<f4').tobytes()
    camera.model_info = {'classes': {'Xin_Chao': 0, 'Tam_Biet': 1}, 'sha256': 'test-model'}
    event = uuid4().hex
    with TestClient(app, headers=auth) as client:
        assert client.get('/api/learning/export', headers={'Authorization': 'invalid'}).status_code == 401
        session = client.post('/api/learning/session', json={'enabled': True}).json()['learning']['session']
        assert session == camera.learning_session
        camera.running = True
        camera.recognition = {'status': 'recognized'}
        camera.pending.append({'id': event, 'label': 'xin_chao', 'text': 'Xin chào', 'confirmed': False,
                               'confidence': .8, 'captured_at': time.monotonic(), 'candidates': [],
                               'learning_session': session, 'learning_features': raw})
        camera.serial += 1
        for _ in range(30):
            candidate = client.get('/api/state').json()['learning']['candidate']
            if candidate:
                break
            time.sleep(.05)
        assert candidate['id'] == event and 'features' not in candidate
        assert client.post('/api/learning/feedback', json={'event': event, 'label': 'unknown'}).status_code == 422
        assert client.post('/api/learning/freeze', json={'event': event}).status_code == 200
        camera.recognition = {'status': 'no_hands'}
        assert client.get('/api/state').json()['learning']['candidate'] is None
        assert client.delete(f'/api/learning/freeze/{event}').status_code == 200
        assert client.post('/api/learning/feedback', json={'event': event, 'label': 'Tam_Biet'}).status_code == 409
        camera.recognition = {'status': 'recognized'}
        camera.pending.append({'id': event, 'label': 'xin_chao', 'text': 'Xin chào', 'confirmed': False,
                               'confidence': .8, 'captured_at': time.monotonic(), 'candidates': [],
                               'learning_session': session, 'learning_features': raw})
        camera.serial += 1
        for _ in range(30):
            if client.get('/api/state').json()['learning']['candidate']:
                break
            time.sleep(.05)
        assert client.post('/api/learning/freeze', json={'event': event}).status_code == 200
        camera.recognition = {'status': 'no_hands'}
        feedback = {'event': event, 'label': 'Tam_Biet'}
        assert client.post('/api/learning/feedback', json=feedback).status_code == 200
        assert client.post('/api/learning/feedback', json=feedback).status_code == 200
        assert not client.get('/api/learning/export').json()['samples']
        assert client.post(f'/api/learning/samples/{event}', json={'action': 'approved'}).status_code == 200
        row, = client.get('/api/learning/export').json()['samples']
        assert row['predicted'] == 'Xin_Chao' and row['label'] == 'Tam_Biet' and row['session'] == session
        assert base64.b64decode(row['features']) == raw
        assert client.post('/api/learning/session', json={'enabled': False}).json()['learning']['session'] is None

def test_mobile_feedback_requires_opt_in_auth_model_and_is_idempotent(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setenv('DAKT_API_TOKEN', 'test-learning')
    monkeypatch.delenv('DAKT_MOBILE_FEEDBACK', raising=False)
    monkeypatch.setattr('server.ROOT', tmp_path)
    app = create_app(tmp_path / 'mobile.sqlite3')
    app.state.camera.model_info = {'classes': {'Xin_Chao': 0, 'Tam_Biet': 1}, 'sha256': 'a' * 64}
    raw = np.full((30, 126), .25, dtype='<f4').tobytes()
    event = uuid4().hex
    payload = dict(event=event, label='Tam_Biet', predicted='Xin_Chao', confidence=.85,
                   device_id=uuid4().hex, session_id=uuid4().hex, version=1,
                   captured_at=datetime.now(timezone.utc).isoformat(), model_sha256='a' * 64,
                   features=base64.b64encode(raw).decode())
    path = '/api/learning/mobile-feedback'
    with TestClient(app, headers={'Authorization': 'Bearer test-learning'}) as client:
        assert client.post(path, json=payload).status_code == 404
        monkeypatch.setenv('DAKT_MOBILE_FEEDBACK', '1')
        assert client.post(path, json=payload, headers={'Authorization': 'invalid'}).status_code == 401
        assert client.post(path, json=dict(payload, model_sha256='b' * 64)).status_code == 409
        assert client.post(path, json=dict(payload, features='!' * 20160)).status_code == 422
        assert client.post(path, json=dict(payload, label='unknown')).status_code == 422
        assert client.post(path, json=payload).json() == {'status': 'pending_review'}
        assert client.post(path, json=payload).status_code == 200
        assert client.post(path, json=dict(payload, label='Xin_Chao')).status_code == 409
        row, = client.get('/api/learning/samples').json()['items']
        assert row['status'] == 'pending' and row['session'] == payload['device_id'] + '/' + payload['session_id']
        assert client.get('/api/state').json()['learning']['session'] is None
        assert client.get('/api/learning/export').json()['samples'] == []
