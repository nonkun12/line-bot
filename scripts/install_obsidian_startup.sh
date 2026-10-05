#!/bin/zsh
set -euo pipefail
REPO_ROOT="$HOME/line-bot"
PLIST="$HOME/Library/LaunchAgents/com.line-ai-secretary.obsidian-startup.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.line-ai-secretary.obsidian-startup</string>
<key>ProgramArguments</key><array>
<string>/bin/zsh</string><string>-lc</string>
<string>cd "$REPO_ROOT" && if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then exec "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/obsidian_mac_startup.py"; else exec /usr/bin/python3 "$REPO_ROOT/scripts/obsidian_mac_startup.py"; fi</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><false/>
<key>ProcessType</key><string>Background</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed: $PLIST"
echo "Runs once at login; no polling."
