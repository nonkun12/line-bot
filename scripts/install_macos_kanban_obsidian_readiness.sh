#!/bin/zsh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: python3 was not found. No LaunchAgent was installed." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "ERROR: Python 3.10+ is required. No LaunchAgent was installed." >&2
  exit 1
fi

export REPO_ROOT PYTHON_BIN
"$PYTHON_BIN" - <<'PY'
import os
import plistlib
from pathlib import Path

home = Path.home()
repo = Path(os.environ["REPO_ROOT"]).resolve()
python = os.environ["PYTHON_BIN"]
script = repo / "scripts" / "macos_kanban_obsidian_readiness.py"
if not script.is_file():
    raise SystemExit("ERROR: readiness script not found; no LaunchAgent was installed.")

label = "com.line-ai-secretary.kanban-obsidian-readiness"
agent_dir = home / "Library" / "LaunchAgents"
log_dir = home / ".local" / "state" / "line-ai-secretary"
agent_dir.mkdir(parents=True, exist_ok=True)
log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    log_dir.chmod(0o700)
except OSError:
    pass

payload = {
    "Label": label,
    "ProgramArguments": [python, str(script)],
    "RunAtLoad": True,
    "KeepAlive": False,
    "ProcessType": "Background",
    "StandardOutPath": str(log_dir / "kanban-obsidian-readiness.stdout.log"),
    "StandardErrorPath": str(log_dir / "kanban-obsidian-readiness.stderr.log"),
}
plist_path = agent_dir / f"{label}.plist"
with plist_path.open("wb") as handle:
    plistlib.dump(payload, handle, sort_keys=True)
try:
    plist_path.chmod(0o600)
except OSError:
    pass
print(f"Created LaunchAgent: {plist_path}")
PY

PLIST="$HOME/Library/LaunchAgents/com.line-ai-secretary.kanban-obsidian-readiness.plist"
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed: $PLIST"
echo "The read-only audit runs once at user login; it does not poll, call external APIs, edit repositories, or start workers."
echo "Report: $HOME/.local/state/line-ai-secretary/kanban-obsidian-readiness-latest.json"
