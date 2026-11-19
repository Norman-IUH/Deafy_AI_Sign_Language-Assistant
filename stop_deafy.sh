#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$PROJECT_DIR/.tools/deafy-logs"
exec 9>"$PROJECT_DIR/.tools/deafy-logs/launcher.lock"
flock -w 15 9 || { echo 'Đang khởi động Deafy, thử dừng lại sau.' >&2; exit 1; }
unit_file="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/signassist-connected.service"
if [ ! -f "$unit_file" ] || ! grep -Fq -- "$PROJECT_DIR/start_pi.sh" "$unit_file"; then
  echo 'Không có service thuộc checkout này; không dừng tiến trình khác.' >&2
  exit 1
fi
if systemctl --user is-active --quiet deafy-ui.service; then systemctl --user stop deafy-ui.service; fi
pwa_unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/deafy-pwa.service"
if [ -f "$pwa_unit" ] && grep -Fq '# Deafy managed PWA HTTPS' "$pwa_unit" && grep -Fq -- "$PROJECT_DIR/.tools/pwa-https" "$pwa_unit"; then
  systemctl --user stop deafy-pwa.service
fi
systemctl --user stop signassist-connected.service
echo 'Đã dừng Deafy: backend, inference, camera, microphone và UI do launcher mở.'
echo 'Broker MQTT dùng chung và các cửa sổ trình duyệt khác được giữ nguyên.'
