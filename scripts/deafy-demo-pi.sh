#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
case "${1:-start}" in
  start) bash "$root/start_deafy.sh" --kiosk ;;
  stop) bash "$root/stop_deafy.sh" ;;
  restart)
    if systemctl --user is-active --quiet signassist-connected.service; then
      bash "$root/stop_deafy.sh"
    fi
    bash "$root/start_deafy.sh" --kiosk ;;
  check)
    result=$(python3 "$root/scripts/deafy-demo-health.py" 2>&1)
    printf '%s\n' "$result"
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null; then
      zenity --info --title='Kiểm tra Deafy' --text="$result" --width=480 || true
    fi ;;
  *) exit 2 ;;
esac
