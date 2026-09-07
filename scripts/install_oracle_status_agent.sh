#!/bin/bash
set -euo pipefail

STATUS_URL="${1:-}"
SECRET="${2:-}"
if [ -z "$STATUS_URL" ] || [ -z "$SECRET" ]; then
  echo "Usage: $0 <status-url> <secret>"
  exit 1
fi

BASE="/opt/line-ai-secretary"
sudo mkdir -p "$BASE"
sudo curl -fsSL "https://raw.githubusercontent.com/nonkun12/line-bot/main/scripts/oracle_status_agent.py" -o "$BASE/oracle_status_agent.py"
sudo chmod 755 "$BASE/oracle_status_agent.py"

sudo tee /etc/line-ai-secretary.env >/dev/null <<EOF
ORACLE_STATUS_URL=$STATUS_URL
ORACLE_STATUS_SECRET=$SECRET
EOF
sudo chmod 600 /etc/line-ai-secretary.env

sudo tee /etc/systemd/system/line-ai-secretary-oracle.service >/dev/null <<'EOF'
[Unit]
Description=LINE AI Secretary Oracle status agent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/line-ai-secretary.env
ExecStart=/usr/bin/python3 /opt/line-ai-secretary/oracle_status_agent.py
EOF

sudo tee /etc/systemd/system/line-ai-secretary-oracle.timer >/dev/null <<'EOF'
[Unit]
Description=Send Oracle status to LINE AI Secretary dashboard

[Timer]
OnBootSec=20s
OnUnitActiveSec=30s
Unit=line-ai-secretary-oracle.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now line-ai-secretary-oracle.timer
sudo systemctl start line-ai-secretary-oracle.service
sudo systemctl --no-pager status line-ai-secretary-oracle.timer
