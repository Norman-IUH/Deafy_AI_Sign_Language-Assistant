"""Reviewed training jobs for the course Pi. Training executes on the laptop."""
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import time
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException

MAX_PACKAGE = 8 * 1024 * 1024
ID = re.compile(r'[a-f0-9]{32}')
WATCHED = {'xin_chao', 'tam_biet', 'chao', 'bat_den', 'tat_den'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as target:
        json.dump(value, target, ensure_ascii=False)
    os.replace(target.name, path)


class CourseTraining:
    def __init__(self, store, learning, camera):
        self.store = store
        self.learning = learning
        self.camera = camera
        self.root = camera.root.parent
        self.jobs = store.path.parent / 'course-training'
        self.versions = self.root / 'artifacts/course-models'
        self.agent = None
        self.last_seen = 0

    def model(self):
        path = self.camera.deafy_checkpoint
        if not path.is_file():
            return None, []
        if self.camera.model_info:
            return self.camera.model_info['sha256'], list(self.camera.model_info['classes'])
        for name in ('split_manifest.json', 'evaluation.json'):
            sidecar = path.with_name(name)
            if sidecar.is_file():
                metadata = json.loads(sidecar.read_text(encoding='utf-8'))
                labels = list(metadata.get('class_to_idx') or metadata.get('labels') or [])
                return sha(path.read_bytes()), labels
        return None, []

    def readiness(self):
        baseline, labels = self.model()
        with self.store.connect() as db:
            counts = [dict(row) for row in db.execute(
                'SELECT label,status,COUNT(*) AS total FROM gesture_samples GROUP BY label,status')]
            groups = [dict(row) for row in db.execute(
                """SELECT session,label,COUNT(*) AS total FROM gesture_samples
                   WHERE model=? AND status='approved' GROUP BY session,label""", (baseline,))]
        sessions = {row['session'] for row in groups}
        coverage = {label: sum(row['total'] for row in groups if row['label'] == label) for label in labels}
        full = sorted(session for session in sessions
                      if labels and set(labels) <= {row['label'] for row in groups
                                                   if row['session'] == session and row['total'] >= 2})
        ready = len(full) >= 2 and len(sessions) >= 3
        return {'counts': counts, 'sessions': len(sessions), 'ready': ready, 'baseline': baseline,
                'coverage': coverage, 'can_trial': len(sessions) >= 3 and any(n >= 20 for n in coverage.values()),
                'evaluation_sessions': full, 'target_per_label': 20,
                'approved_for_model': sum(row['total'] for row in groups)}

    def job_path(self, job):
        if not ID.fullmatch(job) or not (self.jobs / job / 'job.json').is_file():
            raise HTTPException(404, 'Không tìm thấy lượt huấn luyện.')
        return self.jobs / job

    def read_job(self, folder):
        return json.loads((folder / 'job.json').read_text(encoding='utf-8'))

    def jobs_list(self):
        return sorted((self.read_job(path.parent) for path in self.jobs.glob('*/job.json')),
                      key=lambda job: job['created'], reverse=True)

    def status(self):
        jobs = self.jobs_list()
        versions = []
        for path in sorted(self.versions.glob('*/training-version.json'), reverse=True):
            version = json.loads(path.read_text(encoding='utf-8'))
            version['active'] = (path.parent / 'candidate.pth').resolve() == self.camera.deafy_checkpoint.resolve()
            versions.append(version)
        return {**self.readiness(), 'agent_online': bool(self.agent and time() - self.last_seen < 20),
                'job': jobs[0] if jobs else None, 'versions': versions}

    def prepare(self):
        ready = self.readiness()
        if not ready['ready']:
            raise HTTPException(409, 'Cần ba phiên riêng, trong đó hai phiên có ít nhất hai mẫu đã duyệt cho mỗi nhãn.')
        if any(job['status'] in ('queued', 'running') for job in self.jobs_list()):
            raise HTTPException(409, 'Đang có một lượt huấn luyện.')
        job = uuid4().hex
        validation, test = ready['evaluation_sessions'][:2]
        data = self.learning.export()
        data['samples'] = [row for row in data['samples']
                           if row['status'] == 'approved' and row['model'] == ready['baseline']]
        # Recheck after materializing the export so the plan and payload describe the same samples.
        eval_labels = self.model()[1]
        if (not any(row['session'] not in (validation, test) for row in data['samples'])
                or any(sum(row['session'] == session and row['label'] == label for row in data['samples']) < 2
                       for session in (validation, test) for label in eval_labels)):
            raise HTTPException(409, 'Kho mẫu vừa thay đổi. Hãy chuẩn bị lại.')
        data['training'] = {'id': job, 'baseline': ready['baseline'], 'validation': validation, 'test': test,
                            'labels': eval_labels}
        folder = self.jobs / job
        folder.mkdir(parents=True, mode=0o700)
        write_json(folder / 'dataset.json', data)
        state = {'id': job, 'created': time(), 'status': 'prepared', 'epoch': 0, 'epochs': 5,
                 'baseline': ready['baseline'], 'dataset_sha256': sha((folder / 'dataset.json').read_bytes())}
        write_json(folder / 'job.json', state)
        return state

    def reset(self, job):
        folder = self.job_path(job)
        state = self.read_job(folder)
        if state['status'] not in ('failed', 'queued', 'running') or (
                state['status'] != 'failed' and self.status()['agent_online']
                and state.get('agent', self.agent) == self.agent):
            raise HTTPException(409, 'Laptop vẫn xử lý hoặc lượt này đã hoàn tất.')
        state.update(status='prepared', epoch=0)
        state.pop('agent', None)
        state.pop('error', None)
        write_json(folder / 'job.json', state)

    def start(self, job):
        if not self.status()['agent_online']:
            raise HTTPException(409, 'Laptop chưa kết nối. Bạn có thể tải gói dữ liệu.')
        folder = self.job_path(job)
        state = self.read_job(folder)
        if state['status'] != 'prepared' or any(item['status'] in ('queued', 'running') for item in self.jobs_list()):
            raise HTTPException(409, 'Lượt này không còn sẵn sàng hoặc có lượt khác đang chạy.')
        state['status'] = 'queued'
        write_json(folder / 'job.json', state)

    def poll(self, agent):
        if self.agent != agent and self.agent and time() - self.last_seen < 20:
            raise HTTPException(409, 'Một laptop khác đang kết nối.')
        self.agent, self.last_seen = agent, time()
        for state in self.jobs_list():
            if state['status'] == 'queued':
                state.update(status='running', agent=agent)
                write_json(self.job_path(state['id']) / 'job.json', state)
                return state
        return None

    def agent_update(self, job, agent, epoch, failed):
        folder = self.job_path(job)
        state = self.read_job(folder)
        if state['status'] != 'running' or state.get('agent') != agent:
            raise HTTPException(409, 'Laptop không sở hữu lượt này.')
        if epoch < state['epoch'] or epoch > state['epochs']:
            raise HTTPException(422, 'Tiến độ không hợp lệ.')
        if self.agent is None or self.agent == agent:
            self.agent, self.last_seen = agent, time()
        state['epoch'] = epoch
        if failed:
            state['status'] = 'failed'
            state['error'] = 'Huấn luyện trên laptop thất bại. Xem thông báo trên laptop.'
        write_json(folder / 'job.json', state)

    def import_model(self, job, payload, agent=None):
        folder = self.job_path(job)
        state = self.read_job(folder)
        if state['status'] == 'complete':
            return
        if (state['status'] not in ('prepared', 'failed', 'running')
                or state['status'] == 'running' and state.get('agent') != agent):
            raise HTTPException(409, 'Lượt này không thể nhập model.')
        try:
            with ZipFile(BytesIO(payload)) as bundle:
                limits = {'candidate.pth': 6 * 1024 * 1024, 'evaluation.json': 200_000}
                if sorted(bundle.namelist()) != sorted(limits) or any(
                    entry.file_size > limits[entry.filename] for entry in bundle.infolist()
                ):
                    raise ValueError('Invalid archive')
                candidate = bundle.read('candidate.pth')
                report = json.loads(bundle.read('evaluation.json'))
            plan = json.loads((folder / 'dataset.json').read_bytes())['training']
            if (not candidate or report['candidate_sha256'] != sha(candidate) or report['baseline_sha256'] != state['baseline']
                    or report['feedback_sha256'] != state['dataset_sha256']
                    or type(report['passes_quality_gate']) is not bool
                    or set(report['labels']) != set(plan['labels'])
                    or report['validation_sessions'] != [plan['validation']]
                    or report['test_sessions'] != [plan['test']]):
                raise ValueError('Report does not match the package')
            old, new = report['baseline'], report['candidate']
            for result in (old, new):
                scores = [result[key] for key in ('accuracy', 'macro_f1')]
                for label in plan['labels']:
                    stats = result['classes'][label]
                    if type(stats['support']) is not int or stats['support'] < 2:
                        raise ValueError('Missing independent test samples')
                    scores.extend(stats[key] for key in ('precision', 'recall', 'f1'))
                if not all(type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1 for score in scores):
                    raise ValueError('Invalid metric')
            if any(old['classes'][label]['support'] != new['classes'][label]['support'] for label in plan['labels']):
                raise ValueError('Test sets do not match')
            gate = (all(new[key] >= old[key] - .02 for key in ('accuracy', 'macro_f1')) and
                    all(new['classes'][label]['f1'] >= old['classes'][label]['f1'] - .05
                        for label in plan['labels'] if label.casefold() in WATCHED))
            if gate != report['passes_quality_gate']:
                raise ValueError('Quality decision does not match the report')
        except (BadZipFile, KeyError, ValueError, TypeError, OSError, RuntimeError):
            raise HTTPException(422, 'Gói model hoặc báo cáo không khớp dữ liệu đã chuẩn bị.') from None
        self.versions.mkdir(parents=True, exist_ok=True)
        version = self.versions / job
        with tempfile.TemporaryDirectory(dir=self.versions) as temporary:
            staging = Path(temporary) / job
            staging.mkdir()
            (staging / 'candidate.pth').write_bytes(candidate)
            write_json(staging / 'evaluation.json', report)
            write_json(staging / 'training-version.json', {'id': job, 'created': time(),
                       'quality': report['passes_quality_gate'], 'pi_check': 'pending',
                       'baseline': state['baseline'], 'dataset_sha256': state['dataset_sha256']})
            if not version.exists():
                staging.rename(version)
        state.update(status='complete', epoch=state['epochs'])
        write_json(folder / 'job.json', state)

    def version_path(self, version):
        path = self.versions / version
        if not ID.fullmatch(version) or not (path / 'training-version.json').is_file():
            raise HTTPException(404, 'Không tìm thấy phiên bản.')
        return path

    def evaluation(self, version):
        path = self.version_path(version)
        report = json.loads((path / 'evaluation.json').read_text(encoding='utf-8'))
        profile = path / 'pi-profile.json'
        return {'report': report, 'profile': json.loads(profile.read_text(encoding='utf-8')) if profile.exists() else None}

    def operation(self, version, action):
        path = self.version_path(version)
        metadata = path / 'training-version.json'
        state = json.loads(metadata.read_text(encoding='utf-8'))
        active = self.camera.deafy_checkpoint.resolve() == (path / 'candidate.pth').resolve()
        if action not in ('check', 'activate', 'rollback'):
            raise HTTPException(404, 'Thao tác model không hợp lệ.')
        if action == 'rollback' and (not active or not (path / 'previous-model.json').is_file()):
            raise HTTPException(409, 'Phiên bản này chưa có model để khôi phục.')
        if action != 'rollback' and (active or not state['quality'] or self.model()[0] != state['baseline']
                                     or action == 'activate' and state['pi_check'] != 'passed'):
            raise HTTPException(409, 'Phiên bản chưa vượt qua kiểm tra hoặc không khớp model đang chạy.')
        if sys.platform != 'linux' or not Path('/proc/device-tree/model').is_file():
            raise HTTPException(409, 'Chỉ kiểm tra và đổi model trên Raspberry Pi của môn học.')
        try:
            # The unit must survive restarting the FastAPI service that received this request.
            subprocess.run(['systemd-run', '--user', '--collect', '--quiet', '--unit=deafy-course-model',
                            '--property=RuntimeMaxSec=210', '--property=Nice=10',
                            sys.executable, str(self.root / 'scripts/course_model.py'),
                            f'ui-{action}', str(path)], check=True, timeout=4, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            raise HTTPException(409, 'Pi không thể bắt đầu thao tác. Có thể một kiểm tra khác đang chạy.') from None
