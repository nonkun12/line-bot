"""Shared GitHub-backed emergency stop for LINE and PC operators.

The dedicated ref is the single source of truth:
refs/heads/control-tower-emergency-stop
Creating it stops runners; deleting it only clears the stop and never starts work.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

STOP_REF = "refs/heads/control-tower-emergency-stop"
API_VERSION = "2022-11-28"


def _request(method: str, repository: str, token: str, path: str, payload: dict | None = None):
    if not token:
        raise RuntimeError("missing_github_token")
    url = f"https://api.github.com/repos/{repository}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "line-bot-emergency-stop",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, {}
        if exc.code == 422:
            return 422, {}
        raise RuntimeError(f"github_http_{exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"github_request_{type(exc).__name__}") from exc


def get_status(repository: str, token: str) -> bool:
    status, _ = _request("GET", repository, token, "/git/ref/heads/control-tower-emergency-stop")
    if status == 200:
        return True
    if status == 404:
        # A missing ref is RUNNING only after the repository itself is confirmed
        # to exist. GitHub also returns 404 for inaccessible or misspelled repos.
        repo_status, repo_payload = _request("GET", repository, token, "")
        if repo_status == 200 and isinstance(repo_payload, dict):
            return False
        raise RuntimeError("stop_status_unconfirmed_repository")
    raise RuntimeError("stop_status_unconfirmed")


def activate_stop(repository: str, token: str) -> str:
    status, main_ref = _request("GET", repository, token, "/git/ref/heads/main")
    if status != 200 or not isinstance(main_ref.get("object"), dict):
        raise RuntimeError("main_sha_unavailable")
    sha = main_ref["object"].get("sha")
    if not isinstance(sha, str) or len(sha) != 40:
        raise RuntimeError("main_sha_invalid")
    status, payload = _request(
        "POST", repository, token, "/git/refs",
        {"ref": STOP_REF, "sha": sha},
    )
    if status == 422:
        return "ALREADY_STOPPED"
    if status != 201 or payload.get("ref") != STOP_REF:
        raise RuntimeError("stop_activation_unconfirmed")
    return "STOPPED"


def clear_stop(repository: str, token: str) -> str:
    status, _ = _request("DELETE", repository, token, "/git/refs/heads/control-tower-emergency-stop")
    if status == 404:
        return "ALREADY_RUNNING"
    if status != 204:
        raise RuntimeError("stop_clear_unconfirmed")
    return "CLEARED"


def local_stop_active(root=None) -> bool:
    """Fail closed when the local emergency stop is set or cannot be inspected."""
    from pathlib import Path
    root_path = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    if os.environ.get("CONTROL_TOWER_KILL_SWITCH", "").strip().casefold() in {"1", "true", "yes", "on"}:
        return True
    configured = os.environ.get("AUTONOMOUS_STOP_FILE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend((root_path / ".autonomous-loop.stop", Path("/tmp/line-bot-autonomous-loop.stop")))
    for candidate in candidates:
        try:
            if candidate.exists():
                return True
        except OSError:
            return True
    return False


def handle_line_command(message: str, user_id: str, token: str, repository: str) -> str | None:
    command = str(message or "").strip().casefold()
    commands = {
        "緊急stop": "stop", "緊急停止": "stop", "emergency stop": "stop",
        "stop状態": "status", "stop状態確認": "status", "停止状態": "status",
        "緊急stop解除": "resume", "緊急停止解除": "resume",
    }
    action = commands.get(command)
    if action is None:
        return None
    allowed = {item.strip() for item in os.environ.get("DEV_ALLOWED_USER_IDS", "").split(",") if item.strip()}
    if not user_id or user_id not in allowed:
        return "緊急STOP操作は許可されていません。"
    try:
        if action == "stop":
            result = activate_stop(repository, token)
            return "🛑 緊急STOPを有効化しました。実行中の自動Loopは停止信号を検知して中断し、新規実行・書き込みを禁止します。" if result == "STOPPED" else "🛑 緊急STOPは既に有効です。"
        if action == "status":
            return "🛑 緊急STOP中です。自動実行は禁止されています。" if get_status(repository, token) else "緊急STOPは解除状態です。"
        result = clear_stop(repository, token)
        return "緊急STOPを解除しました。自動実行は再開しません。次回は新しい承認が必要です。" if result == "CLEARED" else "緊急STOPは既に解除されています。"
    except RuntimeError as exc:
        return f"緊急STOP状態を確定できませんでした。安全のため実行は停止扱いです（{exc}）。"


def _cli_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], check=True, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control the shared LINE/PC emergency stop.")
    parser.add_argument("action", choices=("stop", "status", "resume"))
    parser.add_argument("--repo", default=os.environ.get("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot"))
    args = parser.parse_args(argv)
    token = _cli_token()
    try:
        if args.action == "stop":
            result = activate_stop(args.repo, token)
            print("🛑 STOPPED" if result == "STOPPED" else "🛑 ALREADY_STOPPED")
        elif args.action == "status":
            print("STOPPED" if get_status(args.repo, token) else "RUNNING")
        else:
            result = clear_stop(args.repo, token)
            print("STOP CLEARED; execution does not auto-resume" if result == "CLEARED" else "ALREADY_RUNNING")
        return 0
    except RuntimeError as exc:
        print(f"BLOCKED: stop state unconfirmed ({exc})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
