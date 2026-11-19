#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
desktop_dir=$(xdg-user-dir DESKTOP)
mkdir -p "$desktop_dir" "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
python3 - "$PROJECT_DIR" "$desktop_dir" "${XDG_DATA_HOME:-$HOME/.local/share}/applications" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
def desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
template = (root / 'Deafy AI.desktop').read_text()
for directory in sys.argv[2:]:
    target = Path(directory) / 'Deafy AI.desktop'
    command = 'Exec=/usr/bin/bash ' + desktop_quote(root / 'scripts/deafy-demo-pi.sh')
    text = template
    for action, argument in [('deafy-ai', 'start'), ('deafy-ai-check', 'check'),
                             ('deafy-ai-restart', 'restart'), ('deafy-ai-stop', 'stop')]:
        text = text.replace('Exec=' + action + '\n', command + ' ' + argument + '\n')
    text = text.replace('Icon=deafy-ai', 'Icon=' + str(root / 'scripts/deafy-icon.svg'))
    target.write_text(text); target.chmod(0o755)
print('Đã tạo launcher Deafy AI. Chưa bật tự khởi động.')
PY
gio set "$desktop_dir/Deafy AI.desktop" metadata::trusted true 2>/dev/null || true
