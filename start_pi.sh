#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "$0")"
if [ -f backend/.env.local ]; then
  set -a
  . ./backend/.env.local
  set +a
fi
export PATH="$HOME/.local/bin:$PATH"
if ! command -v node >/dev/null; then
  for node_dir in "$HOME"/.nvm/versions/node/*/bin; do
    [ ! -x "$node_dir/node" ] || export PATH="$node_dir:$PATH"
  done
fi
python_bin=backend/.venv-pi/bin/python
test -x "$python_bin" || { echo 'Chưa có backend/.venv-pi. Xem docs/PI_AI_IOT.md.'; exit 1; }
command -v node >/dev/null || { echo 'Chưa có Node.js. Cài Node 22 LTS rồi chạy lại.'; exit 1; }
node -e 'const [m,n]=process.versions.node.split(".").map(Number); if (!(m===20&&n>=19 || m>=22&&!(m===22&&n<12))) process.exit(1)' || { echo 'Cần Node 20.19+ hoặc 22.12+; ưu tiên Node 22 LTS.'; exit 1; }
test -f RaspberryPi_7inch/node_modules/vite/bin/vite.js || { echo 'Chạy npm ci trong RaspberryPi_7inch trước.'; exit 1; }
"$python_bin" - <<'PY'
import importlib.util, os
from pathlib import Path
modules = ['fastapi', 'uvicorn', 'pydantic', 'markdown_it']
if Path('Deafy_AI_share_ver0/artifacts/step5/run_20261026T045637Z_ebe324f6/best_model.pth').is_file():
    modules += ['torch', 'cv2', 'mediapipe']
if os.getenv('DAKT_MQTT_HOST'):
    modules += ['paho.mqtt.client']
if os.getenv('DAKT_DISCOVERY_ENABLED') == '1':
    modules += ['zeroconf']
engine = os.getenv('DAKT_ASR_ENGINE', 'vosk')
if engine not in ('zipformer', 'whisper', 'vosk'):
    raise SystemExit('DAKT_ASR_ENGINE không được hỗ trợ.')
modules += {'zipformer': ['sherpa_onnx', 'faster_whisper'], 'whisper': ['faster_whisper'], 'vosk': ['vosk']}.get(engine, [])
missing = []
for name in modules:
    try:
        if importlib.util.find_spec(name) is None: missing.append(name)
    except ModuleNotFoundError:
        missing.append(name)
if missing:
    raise SystemExit('Thiếu dependency: ' + ', '.join(missing) + '. Xem HUONG_DAN_CHAY_DEAFY.md.')
print('Dependency Deafy: OK')
PY
bind_host="${DAKT_BIND_HOST:-127.0.0.1}"
if [ -z "${DAKT_BIND_HOST:-}" ] && [ -n "${DAKT_AUDIO_BASE_URL:-}" ]; then bind_host=0.0.0.0; fi
case "$bind_host" in 127.0.0.1|0.0.0.0) ;; *) echo 'DAKT_BIND_HOST phải là 127.0.0.1 hoặc 0.0.0.0.'; exit 1 ;; esac
if [ "$bind_host" = 0.0.0.0 ]; then
  test -n "${DAKT_API_TOKEN:-}" || { echo 'Đặt DAKT_API_TOKEN trước khi mở HTTP LAN.'; exit 1; }
fi
if [ "${1:-}" = --check ]; then exit 0; fi
if [ "${DAKT_MQTT_HOST:-}" = 127.0.0.1 ] && [ -x "$HOME/.local/bin/signassist-mosquitto" ]; then
  # Let the system broker bind first at boot; never race it with the legacy fallback.
  if [ "$(systemctl show mosquitto.service -p LoadState --value 2>/dev/null)" = loaded ]; then
    for attempt in {1..20}; do
      if "$python_bin" -c 'import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(("127.0.0.1",int(sys.argv[1]))))' "${DAKT_MQTT_PORT:-1883}"; then break; fi
      sleep .5
    done
  fi
  if ! "$python_bin" -c 'import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(s.connect_ex(("127.0.0.1",int(sys.argv[1]))))' "${DAKT_MQTT_PORT:-1883}"; then
    systemd-run --user --unit=deafy-mqtt --collect --property=Restart=on-failure \
      "$HOME/.local/bin/signassist-mosquitto" -c "$HOME/.config/signassist/mosquitto.conf"
  fi
fi
"$python_bin" - <<'PY'
import socket
for port in (8001, 5173):
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1', port)) == 0:
            raise SystemExit(f'Cổng {port} đang được dùng. Dùng start_deafy.sh để tái sử dụng dịch vụ, không chạy thêm backend.')
PY
backend_pid=''
frontend_pid=''
cleanup() {
  for child in "$backend_pid" "$frontend_pid"; do
    [ -z "$child" ] || kill -TERM "$child" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
"$python_bin" -m uvicorn server:app --app-dir backend --host "$bind_host" --port 8001 --workers 1 --no-access-log &
backend_pid=$!
node RaspberryPi_7inch/node_modules/vite/bin/vite.js RaspberryPi_7inch --host 127.0.0.1 --port 5173 --strictPort &
frontend_pid=$!
echo 'Sign Assist: http://localhost:5173 — Ctrl+C để dừng.'
wait -n "$backend_pid" "$frontend_pid"
exit 1
