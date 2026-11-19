"""Create a locally reviewed source archive, without mobile weights or private evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'DEAFY_V1_HANDOVER'
FOLDERS = ['backend', 'RaspberryPi_7inch', 'Android_App', 'iPhone_GPS', 'shared',
           'scripts', 'mqtt', 'ESP32_SignAssist', 'Deafy_AI_share_ver0',
           'docs/diagrams', 'docs/demo', 'docs/portfolio', 'docs/release']
EXCLUDE = {'assets/public', 'public/mobile', 'build', 'www', 'node_modules', 'data', 'guide',
           'artifacts', 'downloads', 'samples', 'capacitor-cordova-android-plugins'}
IMAGE_DIRS = ('Android_App/android/app/src/main/res/', 'Android_App/public/icons/',
              'iPhone_GPS/public/icons/')
EXT = {'.py', '.mjs', '.cjs', '.js', '.jsx', '.ts', '.css', '.html', '.md', '.svg', '.json',
       '.conf', '.acl', '.txt', '.lock', '.ini', '.sh', '.bat', '.ps1', '.service', '.desktop',
       '.h', '.cpp', '.java', '.kt', '.xml', '.gradle', '.properties', '.webmanifest', '.pro'}
ODD = {'.gitignore', '.env.example', 'gradlew', 'gradle-wrapper.jar'}
ROOT_FILES = ['.gitignore', '.gitattributes', 'README.md', 'CHANGELOG.md', 'Deafy AI.desktop',
              'start_deafy.sh', 'stop_deafy.sh', 'start_pi.sh', 'START_DEAFY_DEMO.bat',
              'start_cit_tunnel.bat', 'start_pi_preview.bat', 'start_android_preview.bat',
              'start_backend.bat', 'start_all_preview.bat']
PATTERN = re.compile(rb'(?:AIza[A-Za-z0-9_-]{30,}|gsk_[A-Za-z0-9]{30,}|'
                     rb'AQ\.[A-Za-z0-9_-]{35,}|gh[pousr]_[A-Za-z0-9]{30,}|'
                     rb'github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----)')


def candidates():
    for name in ROOT_FILES:
        yield ROOT / name
    yield from ROOT.glob('HUONG_DAN_*.md')
    for folder in FOLDERS:
        for directory, dirs, files in os.walk(ROOT / folder):
            parent = Path(directory)
            dirs[:] = [d for d in dirs if not d.startswith(('.', '__'))
                       and d not in EXCLUDE and '/'.join((parent.name, d)) not in EXCLUDE
                       and not (parent / d).is_symlink()]
            for name in files:
                path = parent / name
                if path.is_symlink() or name in {'secrets.h', 'local.properties', 'keystore.properties',
                                                 'google-services.json', 'PACKAGE_MANIFEST.json',
                                                 'capacitor.plugins.json'}:
                    continue
                if (name in ODD or (not name.startswith('.') and path.suffix.lower() in EXT)
                    or (path.suffix.lower() == '.png' and path.relative_to(ROOT).as_posix().startswith(IMAGE_DIRS))):
                    yield path


def configured_secrets():
    values = set()
    for name in ('backend/.env.local', 'backend/.env', 'ESP32_SignAssist/include/secrets.h'):
        path = ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'\s*(?:#define\s+)?([A-Z_0-9]+)\s*(?:=|\s)\s*(.*)$', line)
            if not match or not re.search(r'KEY|TOKEN|PASSWORD|SECRET|PASS$', match[1]):
                continue
            try:
                parts = shlex.split(match[2], comments=True)
            except ValueError:
                continue
            if parts and len(parts[0]) >= 8:
                values.add(parts[0].encode())
    return values


def main():
    files, hits = {}, []
    known = configured_secrets()
    for path in sorted(set(candidates())):
        name = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        if PATTERN.search(data) or any(secret in data for secret in known):
            hits.append(name)
        files[name] = data
    if hits:
        raise SystemExit('Source blocked by credential scan; values withheld: ' + ', '.join(hits))
    report = {'files_checked': len(files), 'known_configured_values_checked': len(known),
              'credential_hits': 0, 'git_history': 'not available in the workspace',
              'scope': 'portfolio source only; permissions and manual privacy review required'}
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    OUT.mkdir(exist_ok=True)
    with ZipFile(OUT / 'DEAFY_PORTFOLIO_SOURCE.zip', 'w', ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('PORTFOLIO_MANIFEST.json', json.dumps(manifest, indent=2))
    with ZipFile(OUT / 'DEAFY_PORTFOLIO_SOURCE.zip') as archive:
        assert archive.testzip() is None
    (OUT / 'PORTFOLIO_SCAN.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
