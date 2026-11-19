"""Profile and switch reviewed GRU checkpoints on the course Pi 5 4 GB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from time import perf_counter, process_time
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('DAKT_GRU_CHECKPOINT', 'DAKT_GRU_SHA256', 'DAKT_GRU_NAME')
SERVICE = 'signassist-connected.service'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile(path):
    import resource
    import torch
    sys.path.insert(0, str(ROOT / 'Deafy_AI_share_ver0'))
    from step5_train import load_checkpoint
    from step6_inference_pipeline import validate_preprocessing

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    model, checkpoint = load_checkpoint(path)
    validate_preprocessing(checkpoint)
    sample = torch.rand(1, 30, 126, generator=torch.Generator().manual_seed(42))
    timings = []
    with torch.inference_mode():
        for _ in range(10):
            model(sample)
        started, cpu = perf_counter(), process_time()
        for _ in range(120):
            before = perf_counter()
            model(sample)
            timings.append((perf_counter() - before) * 1000)
    return {'sha256': sha(path), 'classes': checkpoint['class_to_idx'],
            'p95_ms': sorted(timings)[113], 'rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            'cpu_percent_one_core': (process_time() - cpu) / (perf_counter() - started) * 100}


def settings(lines):
    values = {}
    for line in lines:
        key, _, raw = line.strip().partition('=')
        if key in KEYS:
            parsed = shlex.split(raw, comments=True)
            if len(parsed) > 1:
                raise ValueError(f'Invalid setting {key}')
            values[key] = parsed[0] if parsed else ''
    return values


def write_settings(path, lines, values):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
        for line in lines:
            if line.strip().partition('=')[0] not in KEYS:
                output.write(line.rstrip('\n') + '\n')
        for key, value in values.items():
            output.write(f'{key}={shlex.quote(value)}\n')
    os.replace(output.name, path)


def require_course_pi(run):
    model = Path('/proc/device-tree/model').read_bytes()
    memory = int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1])
    if b'Raspberry Pi 5' not in model or not 3_500_000 <= memory < 4_500_000:
        raise ValueError('This command is only for the course Raspberry Pi 5 4 GB')
    if run.parent != ROOT / 'artifacts/course-models':
        raise ValueError('Keep the version under artifacts/course-models in the course project')


def check(run, current, cached=False):
    candidate = run / 'candidate.pth'
    report = json.loads((run / 'evaluation.json').read_text(encoding='utf-8'))
    baseline = (ROOT / current['DAKT_GRU_CHECKPOINT']).resolve()
    if (report.get('passes_quality_gate') is not True or report['baseline_sha256'] != sha(baseline)
            or report['candidate_sha256'] != sha(candidate)):
        raise ValueError('Candidate or baseline mismatch, or quality gate failed')
    result = run / 'pi-profile.json'
    if cached:
        report_profile = json.loads(result.read_text(encoding='utf-8'))
        old, new = report_profile['baseline'], report_profile['candidate']
        if old['sha256'] != report['baseline_sha256'] or new['sha256'] != report['candidate_sha256']:
            raise ValueError('Pi performance report no longer matches the checkpoints')
    else:
        env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   OMP_WAIT_POLICY='PASSIVE')
        old, new = [json.loads(subprocess.check_output([sys.executable, __file__, 'profile', str(path)],
                                                       timeout=45, env=env))
                    for path in (baseline, candidate)]
        write_json(result, {'baseline': old, 'candidate': new})
    if (new['classes'] != old['classes'] or new['p95_ms'] > max(5, old['p95_ms'] * 1.2)
            or new['rss_mib'] > old['rss_mib'] + max(32, old['rss_mib'] * .2)):
        raise ValueError('Candidate failed Pi resource or class checks')


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
        json.dump(value, output, ensure_ascii=False)
    os.replace(output.name, path)


def model_values(action, run, current, cached=False):
    candidate = run / 'candidate.pth'
    previous = run / 'previous-model.json'
    if action == 'rollback':
        report = json.loads((run / 'evaluation.json').read_text(encoding='utf-8'))
        if (ROOT / current['DAKT_GRU_CHECKPOINT']).resolve() != candidate:
            raise ValueError('This version is not the configured model')
        values = json.loads(previous.read_text(encoding='utf-8'))
        if set(values) - set(KEYS) or sha(ROOT / values['DAKT_GRU_CHECKPOINT']) != report['baseline_sha256']:
            raise ValueError('Previous checkpoint no longer matches its recorded checksum')
        return values
    check(run, current, cached)
    write_json(previous, current)
    return dict(zip(KEYS, (candidate.relative_to(ROOT).as_posix(), sha(candidate), f'Model học lại {run.name[:8]}')))


def switch(action, run):
    run = run.resolve()
    require_course_pi(run)
    if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', SERVICE]).returncode != 3:
        raise ValueError(f'Stop {SERVICE} before switching the model')
    env = ROOT / 'backend/.env.local'
    lines = env.read_text(encoding='utf-8').splitlines()
    write_settings(env, lines, model_values(action, run, settings(lines)))


def systemctl(action):
    subprocess.run(['systemctl', '--user', action, SERVICE], check=True, timeout=18)


def recover_camera(api, expected, keep_running):
    for _ in range(35):
        try:
            api('/api/health')
            break
        except OSError:
            time.sleep(.4)
    api('/api/camera/start', True)
    for _ in range(45):
        state = api('/api/state')
        camera = state['camera']
        if camera['running'] and camera['has_frame'] and (state['ai']['model'] or {}).get('sha256') == expected:
            if not keep_running:
                api('/api/camera/stop', True)
            return
        if camera['error']:
            break
        time.sleep(.4)
    raise ValueError('Camera or model did not recover')


def ui_operation(action, run):
    run = run.resolve()
    require_course_pi(run)
    metadata = run / 'training-version.json'
    state = json.loads(metadata.read_text(encoding='utf-8'))
    env = ROOT / 'backend/.env.local'
    lines = env.read_text(encoding='utf-8').splitlines()
    current = settings(lines)
    status_key = 'pi_check' if action == 'check' else 'operation'
    state[status_key] = 'running'
    state.pop('error', None)
    write_json(metadata, state)
    try:
        if action == 'check':
            check(run, current)
        else:
            values = model_values(action, run, current, cached=True)
            private = dict(line.strip().split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
            token = shlex.split(private['DAKT_API_TOKEN'], comments=True)[0]
            port = int(shlex.split(private.get('DAKT_HTTP_PORT', '8001'), comments=True)[0])

            def api(path, post=False):
                request = Request(f'http://127.0.0.1:{port}{path}', data=b'{}' if post else None,
                                  headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
                with urlopen(request, timeout=12 if post else 2) as reply:
                    return json.load(reply)

            before = api('/api/state')['camera']['running']
            try:
                systemctl('stop')
                write_settings(env, lines, values)
                systemctl('start')
                recover_camera(api, sha(ROOT / values['DAKT_GRU_CHECKPOINT']), before)
            except Exception:
                try:
                    systemctl('stop')
                finally:
                    write_settings(env, lines, current)
                    systemctl('start')
                recover_camera(api, sha(ROOT / current['DAKT_GRU_CHECKPOINT']), before)
                state['error'] = 'Thao tác thất bại. Đã khôi phục cấu hình trước và kiểm tra lại camera.'
                raise
        state[status_key] = 'passed'
    except Exception:
        state[status_key] = 'failed'
        state.setdefault('error', 'Thao tác thất bại. Xem journalctl --user -u deafy-course-model trên Pi.')
        raise
    finally:
        write_json(metadata, state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('profile', 'activate', 'rollback', 'ui-check', 'ui-activate', 'ui-rollback'))
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    if args.action == 'profile':
        print(json.dumps(profile(args.path)))
    elif args.action.startswith('ui-'):
        ui_operation(args.action[3:], args.path)
    else:
        switch(args.action, args.path)
