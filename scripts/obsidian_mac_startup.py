"""Mac login-time approval gate for pending Obsidian saves.

Checks once, never polls, and never claims a job during the check.
A human must explicitly choose Execute before the one-shot bridge runs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

ENV_FILE = Path.home() / ".config" / "line-ai-secretary" / "obsidian-bridge.env"
REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = REPO_ROOT / "scripts" / "obsidian_mac_bridge.py"

def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values

def _notify(title: str, message: str) -> None:
    subprocess.run(["/usr/bin/osascript", "-e",
        "display notification " + repr(message) + " with title " + repr(title)],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _ask_execute() -> bool:
    script = 'display dialog "Obsidianへの保存依頼があります。" buttons {"後で", "実行"} default button "後で" with title "LINE AI Secretary"'
    result = subprocess.run(["/usr/bin/osascript", "-e", script], check=False, capture_output=True, text=True)
    return "button returned:実行" in result.stdout

def main() -> int:
    env = _load_env_file(ENV_FILE)
    server_url = env.get("OBSIDIAN_BRIDGE_SERVER_URL", os.environ.get("OBSIDIAN_BRIDGE_SERVER_URL", "")).rstrip("/")
    bridge_key = env.get("OBSIDIAN_BRIDGE_KEY", os.environ.get("OBSIDIAN_BRIDGE_KEY", ""))
    vault_path = env.get("OBSIDIAN_VAULT_PATH", os.environ.get("OBSIDIAN_VAULT_PATH", ""))
    if not server_url or not bridge_key or not vault_path:
        _notify("LINE AI Secretary", "Obsidian設定が不足しています。")
        return 1
    try:
        response = httpx.get(server_url + "/api/obsidian/pending", headers={"X-Obsidian-Bridge-Key": bridge_key}, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return 1
    if payload.get("pending") is not True:
        return 0
    if not _ask_execute():
        return 0
    subprocess.run(["/usr/bin/open", "-a", "Obsidian"], check=False)
    bridge_env = os.environ.copy()
    bridge_env.update({
        "OBSIDIAN_BRIDGE_SERVER_URL": server_url,
        "OBSIDIAN_BRIDGE_KEY": bridge_key,
        "OBSIDIAN_VAULT_PATH": vault_path,
    })
    completed = subprocess.run([sys.executable, str(BRIDGE_SCRIPT)], env=bridge_env, check=False)
    if completed.returncode != 0:
        _notify("LINE AI Secretary", "Obsidian保存処理が完了しませんでした。")
        return completed.returncode
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
