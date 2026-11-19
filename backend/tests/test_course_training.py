from io import BytesIO
import importlib.util
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from course_training import sha
from server import create_app


def test_course_workflow_uses_reviewed_samples_and_explicit_start(tmp_path, monkeypatch):
    monkeypatch.setenv('DAKT_API_TOKEN', 'test-course')
    database = tmp_path / 'course.sqlite3'
    monkeypatch.setattr('server.ROOT', tmp_path / 'project' / 'backend')
    app = create_app(database)
    camera = app.state.camera
    camera.deafy_checkpoint = tmp_path / 'project' / 'model.pth'
    camera.deafy_checkpoint.parent.mkdir()
    camera.deafy_checkpoint.write_bytes(b'original')
    camera.model_info = {'sha256': sha(b'original'), 'classes': ['Xin_Chao']}
    agent, other = uuid4().hex, uuid4().hex
    with TestClient(app, headers={'Authorization': 'Bearer test-course'}) as client:
        base = '/api/training'
        assert client.get(base + '/status', headers={'Authorization': 'wrong'}).status_code == 401
        assert client.post(base + '/prepare').status_code == 409
        import sqlite3
        with sqlite3.connect(database) as db:
            for session, statuses in {'a': ['approved'] * 2, 'b': ['approved'] * 2,
                                      'c': ['approved', 'pending', 'rejected']}.items():
                for status in statuses:
                    row = uuid4().hex
                    db.execute("""INSERT INTO gesture_samples(id,predicted,label,confidence,session,model,digest,features,status)
                                  VALUES(?,?,?,?,?,?,?,?,?)""",
                               (row, 'Xin_Chao', 'Xin_Chao', .9, session, sha(b'original'), row, b'input', status))
        plan = client.post(base + '/prepare').json()
        job = base + '/jobs/' + plan['id']
        assert client.post(job + '/start').status_code == 409
        assert client.post(base + '/agent/' + agent).json() == {'job': None}
        assert client.post(job + '/start').status_code == 200
        assert client.post(job + '/start').status_code == 409
        assert client.post(base + '/agent/' + other).status_code == 409
        assert client.post(base + '/agent/' + agent).json()['job']['status'] == 'running'
        assert client.post(job + '/progress', params={'agent': other, 'epoch': 1}).status_code == 409
        assert client.post(job + '/progress', params={'agent': agent, 'epoch': 1}).status_code == 200
        assert client.post(job + '/progress', params={'agent': agent, 'epoch': 0}).status_code == 422
        assert client.post(job + '/reset').status_code == 409
        dataset = client.get(job + '/dataset')
        assert sha(dataset.content) == plan['dataset_sha256']
        assert len(dataset.json()['samples']) == 5
        assert {row['status'] for row in dataset.json()['samples']} == {'approved'}
        assert client.post(job + '/import', params={'agent': agent}, content=b'invalid').status_code == 422
        model = b'test-checkpoint'
        scores = {'accuracy': 1, 'macro_f1': 1,
                  'classes': {'Xin_Chao': {'precision': 1, 'recall': 1, 'f1': 1, 'support': 2}}}
        report = {'candidate_sha256': sha(model), 'baseline_sha256': sha(b'original'),
                  'feedback_sha256': sha(dataset.content), 'passes_quality_gate': True,
                  'labels': ['Xin_Chao'], 'validation_sessions': ['a'], 'test_sessions': ['b'],
                  'baseline': scores, 'candidate': scores}
        archive = BytesIO()
        with ZipFile(archive, 'w') as bundle:
            bundle.writestr('candidate.pth', model)
            bundle.writestr('evaluation.json', json.dumps(report))
        assert client.post(job + '/import', params={'agent': agent}, content=archive.getvalue()).status_code == 200
        state = client.get(base + '/status').json()
        assert state['job']['status'] == 'complete'
        version, = state['versions']
        assert not version['active'] and version['pi_check'] == 'pending'
        version_path = base + '/versions/' + version['id']
        assert client.post(version_path + '/activate').status_code == 409
        assert client.get(version_path + '/evaluation').json()['report'] == report
        assert camera.deafy_checkpoint.read_bytes() == b'original'


def test_failed_camera_start_restores_model_settings(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / 'scripts/course_model.py'
    spec = importlib.util.spec_from_file_location('course_model', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'require_course_pi', lambda _: None)
    run = tmp_path / 'artifacts/course-models/v1'
    run.mkdir(parents=True)
    metadata = run / 'training-version.json'
    metadata.write_text('{}')
    original, candidate = tmp_path / 'model2.pth', run / 'candidate.pth'
    original.write_bytes(b'model-2')
    candidate.write_bytes(b'candidate')
    env = tmp_path / 'backend/.env.local'
    env.parent.mkdir()
    env.write_text('DAKT_API_TOKEN=test\nDAKT_GRU_CHECKPOINT=model2.pth\n')
    monkeypatch.setattr(module, 'model_values', lambda *_args, **_kwargs: {
        'DAKT_GRU_CHECKPOINT': str(candidate)})
    calls = []
    monkeypatch.setattr(module, 'systemctl', calls.append)
    monkeypatch.setattr(module, 'urlopen', lambda *_args, **_kwargs: BytesIO(b'{"camera":{"running":true}}'))

    def recover(_api, digest, before):
        assert before
        calls.append(digest)
        if digest == sha(b'candidate'):
            raise ValueError('Camera failed')

    monkeypatch.setattr(module, 'recover_camera', recover)
    with pytest.raises(ValueError, match='Camera failed'):
        module.ui_operation('activate', run)
    assert calls == ['stop', 'start', sha(b'candidate'), 'stop', 'start', sha(b'model-2')]
    assert 'DAKT_GRU_CHECKPOINT=model2.pth' in env.read_text()
    state = json.loads(metadata.read_text())
    assert state['operation'] == 'failed' and 'Đã khôi phục' in state['error']
