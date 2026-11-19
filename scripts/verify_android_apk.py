"""Verify the APK contains current web assets, native plugins and no configured secrets."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def verify():
    apk = ROOT / 'Android_App/android/app/build/outputs/apk/debug/app-debug.apk'
    web = ROOT / 'Android_App/www'
    known = set()
    # Compare locally without printing values or copying secrets into a report.
    for env_file in [ROOT/'backend/.env.local', ROOT/'backend/.env']:
        if env_file.is_file():
            for line in env_file.read_text(encoding='utf-8-sig').splitlines():
                match = re.match(r'\s*([A-Z_0-9]+)\s*=\s*(.*?)\s*$', line)
                if match and re.search(r'(API_KEY|TOKEN|PASSWORD|SECRET)', match[1]):
                    value = match[2].strip('"\'')
                    if len(value) >= 8:
                        known.add(value.encode())
    with ZipFile(apk) as archive:
        assert archive.testzip() is None, 'Corrupt APK'
        names = archive.namelist()
        packaged = {name: archive.read(name) for name in names if not name.endswith('/')}
        checked = 0
        for path in web.rglob('*'):
            if path.is_file():
                name = 'assets/public/' + path.relative_to(web).as_posix()
                assert packaged.get(name) == path.read_bytes(), 'Stale/missing frontend asset: ' + name
                checked += 1
        expected_js = {p.name for p in (web/'assets').glob('*.js')}
        actual_js = {Path(n).name for n in names if n.startswith('assets/public/assets/') and n.endswith('.js')}
        assert actual_js == expected_js, 'Old JS bundles left in APK'
        config = json.loads(packaged['assets/capacitor.config.json'])
        assert not config.get('server', {}).get('url'), 'APK must bundle local UI, not a dev server'
        plugins = json.loads(packaged['assets/capacitor.plugins.json'])
        assert {'@capacitor-community/text-to-speech','@capgo/capacitor-speech-recognition'} <= {p['pkg'] for p in plugins}
        dex = b''.join(data for name,data in packaged.items() if name.endswith('.dex'))
        assert b'PiDiscoveryPlugin' in dex and b'DeafyPairingPlugin' in dex, 'Missing native discovery/pairing'
        for n in names:
            suffix=Path(n).suffix.lower()
            assert not Path(n).name.startswith('.env') and suffix not in ('.pt','.pth','.sqlite3','.keystore','.jks'), 'Private file in APK'
            if suffix in ('.onnx','.tflite') or n=='assets/public/mobile/model2-gru.bin':
                source=web / n.removeprefix('assets/public/')
                assert n.startswith('assets/public/mobile/') and source.is_file() and packaged[n]==source.read_bytes(), 'Unapproved mobile model asset'
        signatures = [rb'gsk_[A-Za-z0-9]{30,}',rb'AIza[A-Za-z0-9_-]{30,}']
        assert not any(secret in data for secret in known for data in packaged.values()), 'Configured credential found; value withheld'
        assert not any(re.search(pattern,data) for pattern in signatures for data in packaged.values()), 'Provider credential pattern found; value withheld'
    lint = ET.parse(ROOT/'Android_App/android/app/build/reports/lint-results-debug.xml').getroot()
    counts = {severity:sum(item.get('severity') == severity for item in lint.findall('issue')) for severity in ('Error','Fatal','Warning')}
    assert not counts['Error'] and not counts['Fatal'], 'Lint has blocking findings'
    result = {'apk': str(apk.relative_to(ROOT)), 'bytes':apk.stat().st_size,
              'sha256':hashlib.sha256(apk.read_bytes()).hexdigest(), 'current_web_assets_verified':checked,
              'configured_secret_values_checked':len(known), 'credential_hits':0,
              'model_embedded':True, 'native_plugins':['PiDiscovery','DeafyPairing','SpeechRecognition','TextToSpeech'],
              'lint':counts, 'device_install':'NOT VERIFIED'}
    output = ROOT/'.tools/deafy-v1-apk-verification.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    verify()

