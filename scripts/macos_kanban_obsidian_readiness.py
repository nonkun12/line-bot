#!/usr/bin/env python3
"""Read-only macOS readiness audit for the local Kanban + Obsidian setup.

No network calls, provider/API calls, task mutations, git writes, or secrets in logs.
Intended to run once at macOS login through a LaunchAgent.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

LABEL_OBSIDIAN = "com.line-ai-secretary.obsidian-startup"
ENV_FILE = Path.home() / ".config" / "line-ai-secretary" / "obsidian-bridge.env"
LOG_DIR = Path.home() / ".local" / "state" / "line-ai-secretary"
LOG_FILE = LOG_DIR / "kanban-obsidian-readiness.jsonl"
LATEST_FILE = LOG_DIR / "kanban-obsidian-readiness-latest.json"


def _run(args: list[str], *, timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def load_env_file(path: Path) -> dict[str, str]:
    """Read KEY=value lines; callers must never log values from this mapping."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key.replace("_", "").isalnum():
            values[key] = value
    return values


def check_kanban_database(db_path: Path) -> tuple[str, str]:
    """Inspect the existing SQLite board in read-only mode; never create a DB."""
    if not db_path.is_file():
        return "WARN", "Kanban database is not present at the configured local path"
    uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                return "FAIL", "Kanban SQLite quick_check did not return ok"
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "tasks" not in tables:
                return "FAIL", "Kanban database exists but the tasks table is missing"
            counts = conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status"
            ).fetchall()
            task_total = sum(int(count) for _status, count in counts)
            status_text = ",".join(
                f"{str(status)[:32]}:{int(count)}"
                for status, count in sorted(counts, key=lambda pair: str(pair[0]))
            ) or "empty"
            return "PASS", f"SQLite quick_check=ok; tasks={task_total}; statuses={status_text}"
    except (sqlite3.Error, OSError, ValueError) as exc:
        # Report the exception type only; DB content and paths are intentionally omitted.
        return "FAIL", f"Kanban read-only database check failed: {type(exc).__name__}"


def check_repo(name: str, repo: Path) -> dict[str, str]:
    if not repo.is_dir():
        return {"name": name, "status": "WARN", "detail": "repository directory is missing"}
    root = _run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"])
    if root is None or root.returncode != 0:
        return {"name": name, "status": "FAIL", "detail": "directory is not a readable Git repository"}
    sha_result = _run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"])
    branch_result = _run(["git", "-C", str(repo), "branch", "--show-current"])
    status_result = _run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"])
    if any(x is None or x.returncode != 0 for x in (sha_result, branch_result, status_result)):
        return {"name": name, "status": "FAIL", "detail": "Git metadata check failed"}
    dirty_count = len([line for line in (status_result.stdout or "").splitlines() if line.strip()])
    branch = (branch_result.stdout or "").strip() or "detached"
    sha = (sha_result.stdout or "").strip() or "unknown"
    detail = f"branch={branch}; head={sha}; dirty_entries={dirty_count}"
    state = "WARN" if dirty_count else "PASS"
    if dirty_count:
        detail += "; local changes left untouched"
    return {"name": name, "status": state, "detail": detail}


def _add(checks: list[dict[str, str]], name: str, status: str, detail: str) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def collect_checks(home: Path | None = None) -> dict[str, Any]:
    """Collect local-only checks. This function does not alter project repositories."""
    home = home or Path.home()
    line_repo = home / "line-bot"
    hermes_repo = home / "hermes-local" / "hermes-agent"
    checks = [
        check_repo("line_bot_git", line_repo),
        check_repo("hermes_git", hermes_repo),
    ]

    bridge_script = line_repo / "scripts" / "obsidian_mac_bridge.py"
    startup_script = line_repo / "scripts" / "obsidian_mac_startup.py"
    installer_script = line_repo / "scripts" / "install_obsidian_startup.sh"
    for name, path in (
        ("obsidian_bridge_script", bridge_script),
        ("obsidian_startup_checker", startup_script),
        ("obsidian_startup_installer", installer_script),
    ):
        _add(checks, name, "PASS" if path.is_file() else "FAIL",
             "required script is present" if path.is_file() else "required script is missing")

    env_path = home / ".config" / "line-ai-secretary" / "obsidian-bridge.env"
    values = load_env_file(env_path)
    # Environment variables take precedence, but values are never displayed or saved.
    for key in ("OBSIDIAN_BRIDGE_SERVER_URL", "OBSIDIAN_BRIDGE_KEY", "OBSIDIAN_VAULT_PATH"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    required = ("OBSIDIAN_BRIDGE_SERVER_URL", "OBSIDIAN_BRIDGE_KEY", "OBSIDIAN_VAULT_PATH")
    missing = [key for key in required if not values.get(key, "").strip()]
    _add(
        checks,
        "obsidian_bridge_config",
        "FAIL" if missing else "PASS",
        "missing required setting names: " + ",".join(missing) if missing else
        "required setting names are present; values suppressed",
    )

    server_url = values.get("OBSIDIAN_BRIDGE_SERVER_URL", "").strip().rstrip("/")
    valid_url = server_url.startswith("https://") or server_url.startswith(
        ("http://localhost", "http://127.0.0.1")
    )
    _add(
        checks,
        "obsidian_server_url_policy",
        "PASS" if not server_url or valid_url else "FAIL",
        "HTTPS or loopback URL policy satisfied" if not server_url or valid_url else
        "refused: non-HTTPS server URL",
    )

    vault_raw = values.get("OBSIDIAN_VAULT_PATH", "").strip()
    vault = Path(vault_raw).expanduser() if vault_raw else None
    vault_ok = bool(vault and vault.is_dir())
    _add(
        checks,
        "obsidian_vault",
        "PASS" if vault_ok else ("FAIL" if vault_raw else "WARN"),
        "vault directory exists" if vault_ok else
        ("configured vault directory is missing" if vault_raw else "vault path is not configured"),
    )

    kanban_home_value = os.environ.get("HERMES_KANBAN_HOME", "").strip()
    kanban_db_value = os.environ.get("HERMES_KANBAN_DB", "").strip()
    if kanban_db_value:
        db_path = Path(kanban_db_value).expanduser()
    else:
        kanban_home = Path(kanban_home_value).expanduser() if kanban_home_value else home / ".hermes"
        db_path = kanban_home / "kanban.db"
    status, detail = check_kanban_database(db_path)
    _add(checks, "kanban_database", status, detail)

    label = LABEL_OBSIDIAN
    plist = home / "Library" / "LaunchAgents" / f"{label}.plist"
    _add(
        checks,
        "obsidian_login_agent_plist",
        "PASS" if plist.is_file() else "WARN",
        "login approval LaunchAgent plist is present" if plist.is_file() else
        "login approval LaunchAgent plist is missing",
    )
    launchctl = shutil.which("launchctl") or "/bin/launchctl"
    if plist.is_file():
        probe = _run([launchctl, "print", f"gui/{os.getuid()}/{label}"])
        loaded = probe is not None and probe.returncode == 0
        _add(
            checks,
            "obsidian_login_agent_loaded",
            "PASS" if loaded else "WARN",
            "login approval LaunchAgent is registered" if loaded else
            "login approval LaunchAgent is not registered in this user session",
        )
    else:
        _add(checks, "obsidian_login_agent_loaded", "WARN", "not checked because plist is missing")

    states = [check["status"] for check in checks]
    overall = "FAIL" if "FAIL" in states else ("WARN" if "WARN" in states else "PASS")
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "mode": "read-only-local-audit",
        "external_requests": 0,
        "project_writes": 0,
        "checks": checks,
    }


def write_report(report: dict[str, Any]) -> None:
    """Persist a minimal local audit trail outside either project repository."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            LOG_DIR.chmod(0o700)
        except OSError:
            pass
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
        latest_tmp = LATEST_FILE.with_suffix(".json.tmp")
        latest_tmp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        latest_tmp.replace(LATEST_FILE)
        for path in (LOG_FILE, LATEST_FILE):
            try:
                path.chmod(0o600)
            except OSError:
                pass
    except OSError as exc:
        print(f"[WARN] local audit report could not be persisted: {type(exc).__name__}", file=sys.stderr)


def main() -> int:
    report = collect_checks()
    write_report(report)
    print(f"Kanban / Obsidian local readiness: {report['overall']}")
    for check in report["checks"]:
        print(f"[{check['status']}] {check['name']}: {check['detail']}")
    print(f"Local report: {LATEST_FILE}")
    # A failed prerequisite is a hard stop for any caller that chains work after this audit.
    return 1 if report["overall"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
