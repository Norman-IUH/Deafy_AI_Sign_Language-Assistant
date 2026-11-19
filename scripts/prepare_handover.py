"""Prepare the reviewed release candidate without copying deployment secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib,json,re,shutil,shlex

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'DEAFY_V1_HANDOVER'
OUT.mkdir(exist_ok=True)
STAGE=OUT/'source'
STAGE.mkdir(exist_ok=True)
skip={'node_modules','.venv','.venv-pi','.pio','build','www','__pycache__','.pytest_cache','.gradle','.git'}
blocked={'secrets.h','local.properties','google-services.json','communication.sqlite3'}
sources=['backend','RaspberryPi_7inch','Android_App','iPhone_GPS','shared','scripts','mqtt','ESP32_SignAssist']
files=[]
for folder in sources:
    for p in (ROOT/folder).rglob('*'):
        rel=p.relative_to(ROOT)
        if not p.is_file() or set(rel.parts)&skip or p.name in blocked or p.name.startswith('.env') or 'android/app/src/main/assets/public/' in rel.as_posix():
            continue
        if p.suffix.lower() in ('.jks','.keystore','.sqlite3','.log','.apk','.zip','.rar','.pyc'):
            continue
        files.append(p)
for p in (ROOT/'Deafy_AI_share_ver0').glob('*'):
    if p.is_file() and p.suffix in ('.py','.txt','.md'): files.append(p)
for name in ('README.md','CHANGELOG.md','.gitignore','start_deafy.sh','stop_deafy.sh','start_pi.sh','Deafy AI.desktop',
             'START_DEAFY_DEMO.bat','start_cit_tunnel.bat','start_pi_preview.bat','start_android_preview.bat','start_all_preview.bat',
             'HUONG_DAN_CHAY_DEAFY.md','HUONG_DAN_BUILD_APK.md','HUONG_DAN_CIT_VOICE.md'):
    files.append(ROOT/name)
files.extend(p for p in OUT.glob('*') if p.suffix in ('.md','.mmd','.json') and p.name not in ('SOURCE_MANIFEST.json','SECRET_SCAN.json'))
private=[]
for env_file in (ROOT/'backend/.env.local', ROOT/'ESP32_SignAssist/include/secrets.h'):
    if not env_file.is_file(): continue
    for line in env_file.read_text(encoding='utf-8-sig').splitlines():
        match=re.match(r'\s*(?:#define\s+)?([A-Z_0-9]+)\s*(?:=|\s)\s*(.*?)\s*$',line)
        if match and re.search(r'API_KEY|TOKEN|PASSWORD|SECRET',match[1]):
            try: pieces=shlex.split(match[2],comments=True)
            except ValueError: continue
            if pieces and len(pieces[0])>=8:private.append(pieces[0].encode())
signature=re.compile(rb'AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')
hashes={}; hits=[]
for p in sorted(set(files)):
    data=p.read_bytes(); name=p.relative_to(ROOT).as_posix()
    if signature.search(data) or any(secret in data for secret in private):
        hits.append(name); continue
    target=STAGE/name
    target.parent.mkdir(exist_ok=True,parents=True);target.write_bytes(data)
    hashes[name]=hashlib.sha256(data).hexdigest()
if hits:
    raise SystemExit('Credential scan failed in these files; values withheld: '+', '.join(hits))
manifest={'status':'1.0.0-rc1 pending acceptance','files':hashes,
          'excluded':['private configuration','databases','original checkpoints','raw learning data','deployment backups','development environments']}
(OUT/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
(OUT/'SECRET_SCAN.json').write_text(json.dumps({'files_checked':len(hashes),'known_secret_values_checked':len(set(private)),
    'credential_hits':0,'scope':'sanitized source and separately verified APK','private_workspace_backups':'excluded, retained locally'},indent=2),encoding='utf8')
archive=OUT/'SOURCE_CODE_EXPORT.zip'
with ZipFile(archive,'w',ZIP_DEFLATED) as z:
    for name in hashes:z.write(STAGE/name,name)
    z.write(OUT/'SOURCE_MANIFEST.json','SOURCE_MANIFEST.json')
with ZipFile(archive) as z:assert z.testzip() is None
shutil.copy2(archive,ROOT/'PRESENTATION_PACKAGE/SOURCE_CODE_EXPORT.zip')
sums=[]
for p in OUT.glob('*'):
    if p.is_file() and p.name!='SHA256SUMS.txt':sums.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name)
(OUT/'SHA256SUMS.txt').write_text('\n'.join(sorted(sums))+'\n')
print('PASS sanitized files',len(hashes),'credential hits 0; source archive bytes',archive.stat().st_size)
