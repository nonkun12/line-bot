#!/bin/zsh
set -euo pipefail
CONFIG_FILE="$HOME/.config/orca-status.env"
if [[ ! -r "$CONFIG_FILE" ]]; then
  print -u2 "Missing $CONFIG_FILE; create it with ORCA_TERMINAL_HANDLE, ORCA_STATUS_URL and ORCA_STATUS_SECRET."
  exit 1
fi
set -a
source "$CONFIG_FILE"
set +a
: "${ORCA_STATUS_REPO:?Set ORCA_STATUS_REPO in $CONFIG_FILE}"
cd "$ORCA_STATUS_REPO"
exec /usr/bin/env python3 scripts/orca_status_collector.py --publish
