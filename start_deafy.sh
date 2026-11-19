#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$PROJECT_DIR"
mkdir -p .tools/deafy-logs
LOG="$PROJECT_DIR/.tools/deafy-logs/system.log"
fail() {
  echo "$1 — Log: $LOG" >&2
  if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null; then
    zenity --error --title='Deafy AI' --text="$1
Xem log: $LOG" || true
  fi
  exit 1
}
exec 9>.tools/deafy-logs/launcher.lock
flock -w 10 9 || fail 'Đang có một lượt mở Deafy. Vui lòng chờ.'
bash ./start_pi.sh --check >>"$LOG" 2>&1 || fail 'Môi trường chưa sẵn sàng. Xem hướng dẫn cài dependency.'
if [ "${1:-}" = --check ]; then echo 'Deafy: kiểm tra môi trường OK'; exit 0; fi
[[ "${1:-}" =~ ^(--no-ui|--kiosk)?$ ]] || fail 'Tham số hợp lệ: --check, --no-ui, --kiosk.'
systemctl --user show-environment >/dev/null 2>&1 || fail 'Cần đăng nhập phiên desktop của tài khoản Pi.'
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"
python3 - "$PROJECT_DIR" "$unit_dir/signassist-connected.service" "$LOG" <<'PY' || fail 'Không cập nhật được service. Kiểm tra quyền ghi và log.'
from pathlib import Path
import os, subprocess, sys, tempfile, time
root, target, log = sys.argv[1:]
if any(c in root + log for c in '\n\r'):
    raise SystemExit('Đường dẫn dự án không hợp lệ')
def quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
p = Path(target)
old = p.read_text() if p.exists() else ''
if old and '# Deafy AI managed unit' not in old and root + '/start_pi.sh' not in old.replace('%h', str(Path.home())):
    raise SystemExit('Không thay thế service thuộc dự án khác: ' + target)
text = (Path(root) / 'scripts/signassist-connected.service').read_text()
text = text.replace('@PROJECT_DIR@', root.replace('%', '%%'))
text = text.replace('@START_SCRIPT@', quote(root + '/start_pi.sh'))
text = text.replace('@LOG_PATH@', log.replace('%', '%%'))
if old != text:
    with tempfile.NamedTemporaryFile(mode='w', suffix='.service', dir=p.parent, delete=False) as f:
        f.write(text)
        candidate = Path(f.name)
    check = subprocess.run(['systemd-analyze', '--user', 'verify', str(candidate)], capture_output=True, text=True)
    if check.returncode:
        candidate.unlink()
        raise SystemExit(check.stderr)
    if old:
        backup = p.with_name(p.name + '.backup-' + str(time.time_ns()))
        backup.write_text(old); backup.chmod(0o600)
    os.replace(candidate, p)
PY
systemctl --user daemon-reload
if ! systemctl --user is-active --quiet signassist-connected.service; then
  systemctl --user reset-failed signassist-connected.service || true
  systemctl --user start signassist-connected.service || fail 'Không khởi động được backend.'
fi
backend/.venv-pi/bin/python - <<'PY' || fail 'Backend/giao diện chưa sẵn sàng. Không mở UI rỗng.'
import json, time, urllib.request
for _ in range(90):
    try:
        with urllib.request.urlopen('http://127.0.0.1:5173/api/health', timeout=1) as response:
            data = json.load(response)
        if data.get('service') == 'DAKT-Nc' and data.get('ready'):
            break
    except (OSError, ValueError):
        pass
    time.sleep(.5)
else:
    raise SystemExit('Không có health check hợp lệ sau khi chờ khởi động.')
request = urllib.request.Request('http://127.0.0.1:5173/api/camera/start', method='POST')
urllib.request.urlopen(request, timeout=3).read()
for _ in range(120):
    state = json.load(urllib.request.urlopen('http://127.0.0.1:5173/api/state', timeout=2))
    if state['camera']['has_frame'] or state['camera']['error']:
        break
    time.sleep(.25)
if state['camera']['error']:
    print('Camera: ' + state['camera']['error'])
elif not state['camera']['has_frame']:
    print('Camera đang chuẩn bị; kiểm tra trạng thái trên giao diện.')
if not state['ai']['ready']:
    print('Nhận diện: ' + state['ai']['message'])
PY
if [ -f "$unit_dir/deafy-pwa.service" ] && grep -Fq '# Deafy managed PWA HTTPS' "$unit_dir/deafy-pwa.service"; then
  systemctl --user start deafy-pwa.service || echo 'PWA HTTPS chưa sẵn sàng; xem journalctl --user -u deafy-pwa.'
fi
if [ "${1:-}" = --no-ui ]; then echo 'Deafy sẵn sàng: http://localhost:5173'; exit 0; fi
[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || fail 'Không có màn hình desktop. Dùng --no-ui qua SSH.'
browser=$(command -v chromium || command -v chromium-browser || true)
[ -n "$browser" ] || fail 'Chưa cài Chromium.'
if [ "${1:-}" = --kiosk ] && systemctl --user is-active --quiet deafy-ui.service \
  && ! systemctl --user show deafy-ui.service -p ExecStart --value | grep -Fq -- '--kiosk'; then
  systemctl --user stop deafy-ui.service
fi
if ! systemctl --user is-active --quiet deafy-ui.service; then
  for name in DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS; do
    [ -z "${!name:-}" ] || systemctl --user import-environment "$name"
  done
  args=(--app=http://localhost:5173)
  [ "${1:-}" != --kiosk ] || args=(--kiosk http://localhost:5173)
  systemd-run --user --unit=deafy-ui --collect --property=TimeoutStopSec=10 \
    "$browser" --user-data-dir="$PROJECT_DIR/.tools/deafy-browser" --no-first-run "${args[@]}" \
    || fail 'Backend đã chạy nhưng chưa mở được trình duyệt.'
  sleep .5
  systemctl --user is-active --quiet deafy-ui.service || fail 'Chromium chưa chạy được. Kiểm tra phiên desktop.'
fi
echo 'Deafy AI sẵn sàng.'
