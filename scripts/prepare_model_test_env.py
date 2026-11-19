"""Create an independent Windows test venv from the project's working packages."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.venv-model-test'


if __name__ == '__main__':
    python = TARGET / 'Scripts/python.exe'
    if '--check' in sys.argv:
        if Path(sys.prefix).resolve() != TARGET.resolve():
            raise SystemExit('Wrong interpreter: expected .venv-model-test')
        import cv2, mediapipe, torch, fastapi, uvicorn
        for module in (cv2, mediapipe, torch, fastapi, uvicorn):
            if not Path(module.__file__).resolve().is_relative_to(TARGET.resolve()):
                raise SystemExit('Dependency is not isolated: ' + module.__name__)
        versions = {name: importlib.metadata.version(name) for name in ('torch', 'numpy', 'mediapipe', 'opencv-python', 'fastapi', 'uvicorn')}
        if not hasattr(mediapipe, 'solutions'):
            raise SystemExit('MediaPipe solutions API is required by the supplied inference pipeline')
        output = ROOT / '.tools/model-test/environment.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'python': sys.version, 'prefix': str(TARGET), 'versions': versions}, indent=2), encoding='utf-8')
        print(json.dumps(versions))
    else:
        if not python.is_file():
            source = ROOT / 'backend/.venv/Lib/site-packages'
            if not source.is_dir():
                raise SystemExit('Set up backend/.venv from backend/requirements-windows.lock first. No existing environment was changed.')
            print('Preparing independent test environment (copying installed packages, no upgrades)...', flush=True)
            venv.EnvBuilder(with_pip=True).create(TARGET)
            destination = TARGET / 'Lib/site-packages'
            for item in source.iterdir():
                if item.name in ('__pycache__', 'pip') or item.name.startswith('pip-'):
                    continue
                target = destination / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        result = subprocess.run([str(python), str(Path(__file__).resolve()), '--check'])
        raise SystemExit(result.returncode)
