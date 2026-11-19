"""Train a reviewed course dataset on the laptop, manually or by polling the Pi."""
import argparse
from getpass import getpass
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import ssl
import subprocess
import sys
from threading import Thread
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / '.tools/course-training-runs'


def train(args, dataset, package, progress):
    plan = json.loads(dataset.read_bytes())['training']
    paths = [args.baseline] if args.baseline else [
        *ROOT.glob('artifacts_2/artifacts/step5/*/best_model.pth'),
        *RUNS.glob('*/candidate/candidate.pth'),
    ]
    baseline = next((p for p in paths if p.is_file()
                     and hashlib.sha256(p.read_bytes()).hexdigest() == plan['baseline']), None)
    if baseline is None:
        raise ValueError('Thiếu checkpoint đúng với gói dữ liệu. Chỉ định --baseline trên laptop.')
    run = RUNS / uuid4().hex / 'candidate'
    command = [sys.executable, '-u', str(ROOT / 'scripts/train_gesture_feedback.py'),
               '--original', str(args.original), '--baseline', str(baseline), '--feedback', str(dataset),
               '--validation-session', plan['validation'], '--test-session', plan['test'], '--output', str(run)]
    epoch = 0
    messages = Queue()
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace') as child:
        def read_output():
            try:
                for line in child.stdout:
                    messages.put(line)
            finally:
                messages.put(None)

        Thread(target=read_output, daemon=True).start()
        try:
            while True:
                try:
                    line = messages.get(timeout=5)
                except Empty:
                    progress(epoch)
                    continue
                if line is None:
                    break
                print(line.rstrip(), flush=True)
                if line.startswith('EPOCH '):
                    epoch = int(line.split()[1].split('/')[0])
                    progress(epoch)
            if child.wait():
                raise ValueError('Huấn luyện thất bại. Xem lỗi phía trên.')
        finally:
            if child.poll() is None:
                child.terminate()
    with ZipFile(package, 'x', compression=ZIP_DEFLATED) as archive:
        for name in ('candidate.pth', 'evaluation.json'):
            archive.write(run / name, name)
    print(f'Gói kết quả: {package}', flush=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def listen(args):
    parsed = urlsplit(args.pi)
    loopback = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if not parsed.hostname or (parsed.scheme != 'https' and not loopback) or parsed.path not in ('', '/') or any(
            (parsed.username, parsed.password, parsed.query, parsed.fragment)):
        raise ValueError('Dùng URL HTTPS của Pi hoặc HTTP qua SSH tunnel cục bộ.')
    token = os.getenv('DAKT_API_TOKEN') or getpass('Mã truy cập Pi: ')
    if not token:
        raise ValueError('Cần mã truy cập Pi.')
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=args.ca)))
    agent = uuid4().hex
    base = args.pi.rstrip('/') + '/api/training'

    def request(path, data=None):
        headers = {'Authorization': f'Bearer {token}'}
        with opener.open(Request(base + path, data=data, headers=headers), timeout=12) as response:
            return response.read()

    print('Đang kết nối Pi. Nhấn Ctrl+C để dừng.', flush=True)
    connected = False
    while True:
        try:
            job = json.loads(request('/agent/' + agent, b''))['job']
            if not connected:
                print('Đã kết nối Pi. Chờ bạn nhấn Bắt đầu huấn luyện trên Pi.', flush=True)
            connected = True
        except HTTPError as error:
            if error.code == 401:
                raise ValueError('Pi từ chối mã truy cập.') from None
            job, connected = None, False
            print(f'Pi từ chối đăng ký (HTTP {error.code}). Đang thử kết nối lại.', flush=True)
        except OSError:
            if connected:
                print('Mất kết nối Pi. Đang thử kết nối lại.', flush=True)
            job, connected = None, False
        if job:
            path = '/jobs/' + job['id']
            folder = RUNS / f"{job['id']}-{uuid4().hex[:8]}"
            folder.mkdir(parents=True, exist_ok=False)
            dataset, package = folder / 'dataset.json', folder / 'model.zip'
            epoch = 0

            def progress(value, failed=False):
                nonlocal epoch
                epoch = value
                query = urlencode({'agent': agent, 'epoch': epoch, 'failed': str(failed).lower()})
                try:
                    request(f'{path}/progress?{query}', b'')
                except OSError:
                    print('Chưa gửi được tiến độ. Kết quả sẽ được lưu trên laptop.', flush=True)

            try:
                content = request(path + '/dataset')
                if hashlib.sha256(content).hexdigest() != job['dataset_sha256']:
                    raise ValueError('Gói dữ liệu bị sai checksum.')
                dataset.write_bytes(content)
                train(args, dataset, package, progress)
            except (OSError, ValueError, KeyError) as error:
                print(str(error), file=sys.stderr, flush=True)
                progress(epoch, failed=True)
            else:
                try:
                    request(f'{path}/import?agent={agent}', package.read_bytes())
                    print('Đã gửi kết quả. Mở Kết quả đánh giá trên Pi.', flush=True)
                except URLError:
                    print('Pi chưa nhận kết quả. Dùng Nhập gói model trên Pi với file ZIP vừa tạo.', flush=True)
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    online = commands.add_parser('listen')
    online.add_argument('--pi', required=True)
    online.add_argument('--ca', type=Path)
    manual = commands.add_parser('train')
    manual.add_argument('dataset', type=Path)
    manual.add_argument('package', type=Path)
    for command in (online, manual):
        command.add_argument('--baseline', type=Path)
        command.add_argument('--original', type=Path, default=ROOT / 'data/data/raw')
    args = parser.parse_args()
    try:
        if args.command == 'listen':
            listen(args)
        else:
            train(args, args.dataset, args.package, lambda _: None)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
