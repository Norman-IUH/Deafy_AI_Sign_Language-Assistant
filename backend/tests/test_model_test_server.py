from collections import deque
from threading import Lock

from fastapi.testclient import TestClient
import pytest

from model_test_server import create_test_app
from model_test_profiles import PROFILES


class FakeCamera:
    def __init__(self, profile):
        self.profile = profile
        self.running = self.model_ready = False
        self.error = self.model_error = None
        self.lock, self.thread = Lock(), None
        self.info = {'classes': {'An_Com': 0, **({'Hom_Nay': 1} if profile == 'old' else {})}}
        self.recognition, self.results = {}, deque()
        self.frame_count, self.stops = 0, 0

    def start(self): self.running = self.model_ready = True
    def stop(self): self.running = self.model_ready = False; self.stops += 1
    def status(self): return dict(running=self.running, has_frame=self.running, error=None)
    def metrics(self): return {'fps': 30, 'pipeline_ms_median': 10, 'gru_ms_median': 1}
    def frame(self, landmarks): return b'fixture-jpeg' if self.running else None
    def take_result(self): return self.results.popleft() if self.results else None


def test_local_isolation_permissions_and_model_switch_release_camera(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'PRIVATE-TEST-ONLY')
    app = create_test_app('new', tmp_path, 'test-session', FakeCamera)
    headers = {'X-Model-Test-Session': 'test-session'}
    with TestClient(app) as client:
        initial = client.get('/api/state').json()
        assert initial['profile'] == 'new' and 'PRIVATE-TEST-ONLY' not in str(initial)
        assert client.post('/api/camera/start').status_code == 403
        assert client.post('/api/camera/start', headers=headers).status_code == 200
        first = app.state.camera
        assert client.post('/api/model', headers=headers, json={'profile': '../../bad'}).status_code == 422
        assert first.stops == 0
        changed = client.post('/api/model', headers=headers, json={'profile': 'old'})
        assert changed.json()['profile'] == 'old' and first.stops == 1
        assert app.state.camera.running and 'Hom_Nay' in changed.json()['model']['classes']
        assert client.post('/api/pi/control', headers=headers).status_code == 404
        assert client.post('/api/pi/question', headers=headers).status_code == 404
        assert 'same-origin' == client.get('/api/state').headers['cross-origin-resource-policy']
        assert client.get('/api/state', headers={'Host': 'evil.example'}).status_code == 400
        assert client.get('/').status_code == 200 and client.get('/ui/model-test.js').status_code == 200
    assert not app.state.camera.running


def test_changed_checkpoint_rejected_before_camera_stop(tmp_path, monkeypatch):
    app = create_test_app('old', tmp_path, 'test', FakeCamera)
    monkeypatch.setitem(PROFILES, 'new', {**PROFILES['new'], 'sha256': '0'*64})
    with TestClient(app) as client:
        response = client.post('/api/model', headers={'X-Model-Test-Session': 'test'}, json={'profile': 'new'})
        assert response.status_code == 422 and app.state.camera.stops == 0


def test_trial_real_label_validation_event_timing_and_clear(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('model_test_server.monotonic', lambda: clock[0])
    app = create_test_app('new', tmp_path, 'test', FakeCamera)
    headers = {'X-Model-Test-Session': 'test'}
    with TestClient(app) as client:
        client.post('/api/camera/start', headers=headers)
        assert client.post('/api/trial', headers=headers, json={'label': 'Hom_Nay'}).status_code == 422
        app.state.camera.results.append(dict(id='before', label='an_com', confirmed=True, captured_at=99))
        assert client.post('/api/trial', headers=headers, json={'label': 'An_Com'}).status_code == 200
        assert client.post('/api/model', headers=headers, json={'profile': 'old'}).status_code == 409
        app.state.camera.results.append(dict(id='inside', label='an_com', confirmed=True, captured_at=103))
        app.state.camera.frame_count = 50
        clock[0] = 111
        outcome = client.get('/api/state').json()['trials'][0]
        assert outcome['matched'] and outcome['confirmed_labels'] == ['an_com'] and outcome['valid_capture']
        assert (tmp_path / 'trials.jsonl').is_file()
        assert not client.post('/api/events/clear', headers=headers).json()['events']
        client.post('/api/trial', headers=headers, json={'label': None})
        clock[0] = 122
        invalid = client.get('/api/state').json()['trials'][-1]
        assert not invalid['valid_capture']  # No processed frames must not imply a clean no-hands trial.


def test_landmark_capture_api_saves_without_images_and_blocks_switch(tmp_path,monkeypatch):
    import numpy as np
    clock=[100.0]
    monkeypatch.setattr('model_test_server.monotonic',lambda:clock[0])
    class Recording(FakeCamera):
        def begin_capture(self,start,end):self.buffer=dict(frames=np.ones((100,126),np.float32),masks=np.tile([False,True],(100,1)),times=np.arange(100)/10)
        def end_capture(self):return self.buffer
    app=create_test_app('new',tmp_path,'test',Recording)
    headers={'X-Model-Test-Session':'test'}
    body=dict(subject='P03',session='S01',split='validation',condition='normal',kind='gesture',label='An_Com')
    with TestClient(app) as client:
        client.post('/api/camera/start',headers=headers)
        assert client.post('/api/capture',headers=headers,json={**body,'subject':'../bad'}).status_code==422
        started=client.post('/api/capture',headers=headers,json=body)
        assert started.status_code==200 and started.json()['benchmark']['capture']['phase']=='preparing'
        assert client.post('/api/model',headers=headers,json={'profile':'old'}).status_code==409
        clock[0]=113
        state=client.get('/api/state').json()
        assert state['benchmark']['last_capture']['status']=='saved'
        assert len(list(tmp_path.rglob('*.npz')))==1 and not list(tmp_path.rglob('*.jpg'))
        assert state['benchmark']['counts'][0]['count']==1
