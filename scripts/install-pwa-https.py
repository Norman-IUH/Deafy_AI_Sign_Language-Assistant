#!/usr/bin/env python3
"""LAN-only PWA entry point. Does not install/trust a CA on any client or OS."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import ssl
import subprocess
import tarfile
import time
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]


def download(url,limit=70000000):
    with urlopen(Request(url,headers={'User-Agent':'SignAssist-Setup/1.0'}),timeout=45) as response:
        data=response.read(limit+1)
    if len(data)>limit:raise RuntimeError('Unexpected download size')
    return data


def main():
    if platform.system()!='Linux' or platform.machine() not in ('aarch64','arm64'):
        raise SystemExit('Run this installer on the Raspberry Pi ARM64, not Windows.')
    www=ROOT/'Android_App/www'
    assert (www/'manifest.webmanifest').is_file() and (www/'icons/signassist-192.png').is_file(),'Build/upload Android_App/www first'
    private=ROOT/'.tools/pwa-https';private.mkdir(mode=0o700,exist_ok=True)
    for name in ['data','config','public-trust']:(private/name).mkdir(mode=0o700,exist_ok=True)
    binary=Path.home()/'.local/bin/caddy'
    if not binary.is_file():
        release=json.loads(download('https://api.github.com/repos/caddyserver/caddy/releases/latest',1000000))
        archive=next(a for a in release['assets'] if a['name'].endswith('_linux_arm64.tar.gz'))
        checksum=next(a for a in release['assets'] if a['name'].endswith('_checksums.txt'))
        sums=download(checksum['browser_download_url'],1000000).decode()
        expected=next(row.split()[0] for row in sums.splitlines() if row.split()[-1].lstrip('*')==archive['name'])
        data=download(archive['browser_download_url'])
        assert len(expected)==128 and all(c in '0123456789abcdef' for c in expected),'Unexpected Caddy SHA-512 manifest'
        assert hashlib.sha512(data).hexdigest()==expected,'Caddy release checksum mismatch'
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as package:
            member=package.getmember('caddy');assert member.isfile()
            executable=package.extractfile(member).read()
        binary.parent.mkdir(parents=True,exist_ok=True)
        with binary.with_suffix('.new').open('xb') as f:f.write(executable)
        binary.with_suffix('.new').chmod(0o755);os.replace(binary.with_suffix('.new'),binary)
        (private/'download.json').write_text(json.dumps({'release':release['tag_name'],'archive':archive['name'],'archive_sha512':expected,'archive_sha256':hashlib.sha256(data).hexdigest()}))
    config='''# Deafy managed PWA HTTPS
{
 admin off
 auto_https disable_redirects
 skip_install_trust
}
https://deafy.local:8443 {
 tls internal
 header {
  X-Content-Type-Options nosniff
  Referrer-Policy no-referrer
  Permissions-Policy "geolocation=(self)"
 }
 @backend path /api/* /ws
 handle @backend {
  header Cache-Control no-store
  reverse_proxy 127.0.0.1:8001
 }
 handle {
  root * @WWW@
  file_server
 }
}
http://:8080 {
 root * @TRUST@
 @certificate path /signassist-ca.cer
 header @certificate Content-Type application/x-x509-ca-cert
 file_server
}
'''.replace('@WWW@',json.dumps(str(www))).replace('@TRUST@',json.dumps(str(private/'public-trust')))
    path=private/'Caddyfile'
    if path.exists() and not path.read_text().startswith('# Deafy managed PWA HTTPS'):raise RuntimeError('Config belongs to another service')
    candidate=private/'Caddyfile.new';candidate.write_text(config);candidate.chmod(0o600)
    env={**os.environ,'XDG_DATA_HOME':str(private/'data'),'XDG_CONFIG_HOME':str(private/'config')}
    check=subprocess.run([str(binary),'validate','--config',str(candidate),'--adapter','caddyfile'],env=env,capture_output=True,text=True)
    if check.returncode:raise RuntimeError('Caddy configuration invalid: '+check.stderr)
    os.replace(candidate,path)
    unitdir=Path.home()/'.config/systemd/user';unitdir.mkdir(parents=True,exist_ok=True)
    unit=unitdir/'deafy-pwa.service'
    text=f'''# Deafy managed PWA HTTPS
[Unit]
Description=SignAssist iPhone PWA HTTPS on LAN
After=signassist-connected.service
Wants=signassist-connected.service
[Service]
ExecStart={json.dumps(str(binary))} run --config {json.dumps(str(path))} --adapter caddyfile
Environment="XDG_DATA_HOME={private/'data'}"
Environment="XDG_CONFIG_HOME={private/'config'}"
Restart=on-failure
RestartSec=3
UMask=0077
'''
    if unit.exists() and (not unit.read_text().startswith('# Deafy managed PWA HTTPS') or str(private) not in unit.read_text()):raise RuntimeError('Unit belongs to another service/project')
    unit.write_text(text)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','restart','deafy-pwa.service'],check=True)
    certificate=private/'data/caddy/pki/authorities/local/root.crt'
    for _ in range(60):
        if certificate.is_file():break
        time.sleep(.25)
    else:raise RuntimeError('CA not ready; inspect journalctl --user -u deafy-pwa')
    public=private/'public-trust/signassist-ca.cer'
    der=ssl.PEM_cert_to_DER_cert(certificate.read_text());public.write_bytes(der);public.chmod(0o644)
    (private/'public-trust/index.html').write_text('<meta charset="utf-8"><h1>SignAssist — chứng chỉ HTTPS nội bộ</h1><p>Chỉ cài khi bạn chủ động ghép nối Pi của mình và đã đối chiếu fingerprint.</p><a href="/signassist-ca.cer">Tải chứng chỉ CA công khai</a><p>Trang này không phải ứng dụng GPS. Sau khi cài/trust, mở https://deafy.local:8443</p>')
    print(json.dumps({'https':'https://deafy.local:8443','certificate_download':'http://deafy.local:8080/signassist-ca.cer',
        'ca_sha256_der':hashlib.sha256(der).hexdigest(),'client_trust':'REQUIRES_MANUAL_USER_ACTION','GPS':'NOT_VERIFIED_ON_IPHONE'},indent=2))


if __name__=='__main__':main()
