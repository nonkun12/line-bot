"""macOS login-time approval gate for pending Obsidian jobs.

A human must explicitly choose Execute before the one-shot bridge runs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ENV_FILE = Path.home() / ".config" / "line-ai-secretary" / "obsidian-bridge.env"
STARTUP_LOG = Path.home() / "Library" / "Logs" / "line-ai-secretary" / "obsidian-startup.log"
REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = REPO_ROOT / "scripts" / "obsidian_mac_bridge.py"
BRIDGE_DIAGNOSTIC_PREFIX = "OBSIDIAN_BRIDGE_DIAGNOSTIC "
BRIDGE_CATEGORIES = {
    "url_validation_failed", "configuration_error", "render_api_failure",
    "render_http_error", "job_fetch_failed", "render_response_invalid",
    "vault_write_failed", "local_job_rejected", "local_job_failed",
    "job_not_available", "job_completed", "internal_bridge_failure",
    "bridge_interrupted",
}
BRIDGE_OPERATIONS = {"claim", "complete", "client_setup"}
SAFE_EXCEPTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SAFE_FAILURE_REASONS = {
    "invalid_json", "invalid_response", "invalid_job", "invalid_job_claim",
    "invalid_local_agent_result", "vault_not_configured", "intent_rejected",
    "content_too_large", "overwrite_blocked", "operation_rejected",
    "invalid_command", "unspecified", "invalid_completion_result",
}


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _notify(title: str, message: str) -> bool:
    try:
        result = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                "display notification " + repr(message) + " with title " + repr(title),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return result.returncode == 0


def _ask_execute() -> tuple[str | None, int]:
    script = (
        'display dialog "Obsidianへの保存依頼があります。" '
        'buttons {"後で", "実行"} default button "後で" '
        'with title "LINE AI Secretary"'
    )
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, result.returncode
    choice = "execute" if "button returned:実行" in result.stdout else "later"
    return choice, result.returncode


def _log_event(event: str, run_id: str, **details: object) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": run_id,
        "event": event,
        **details,
    }
    line = json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
    try:
        STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            STARTUP_LOG,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as log_file:
                fd = -1
                log_file.write(line)
        finally:
            if fd >= 0:
                os.close(fd)
    except OSError:
        print(line, end="", file=sys.stderr)


def _bridge_environment(
    server_url: str, bridge_key: str, vault_path: str, run_id: str | None = None
) -> dict[str, str]:
    """Pass startup configuration explicitly to the one-shot bridge."""
    bridge_env = os.environ.copy()
    bridge_env.update(
        {
            "OBSIDIAN_BRIDGE_SERVER_URL": server_url,
            "OBSIDIAN_BRIDGE_KEY": bridge_key,
            "OBSIDIAN_VAULT_PATH": vault_path,
        }
    )
    if run_id is not None:
        bridge_env["OBSIDIAN_BRIDGE_RUN_ID"] = run_id
    return bridge_env


def _read_bridge_diagnostics(stderr: str, run_id: str) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    if not isinstance(stderr, str):
        return diagnostics
    for line in stderr.splitlines():
        if not line.startswith(BRIDGE_DIAGNOSTIC_PREFIX):
            continue
        try:
            record = json.loads(line[len(BRIDGE_DIAGNOSTIC_PREFIX):])
        except (TypeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        if record.get("component") != "obsidian_bridge" or record.get("run_id") != run_id:
            continue
        category = record.get("category")
        if not isinstance(category, str) or category not in BRIDGE_CATEGORIES:
            continue
        safe: dict[str, object] = {"category": category}
        operation = record.get("operation")
        if isinstance(operation, str) and operation in BRIDGE_OPERATIONS:
            safe["operation"] = operation
        status = record.get("status")
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
            safe["status"] = status
        exception = record.get("exception")
        if isinstance(exception, str) and SAFE_EXCEPTION_NAME.fullmatch(exception):
            safe["exception"] = exception
        reason = record.get("reason")
        if isinstance(reason, str) and reason in SAFE_FAILURE_REASONS:
            safe["reason"] = reason
        outcome = record.get("outcome")
        if isinstance(outcome, str) and outcome in {"success", "failure"}:
            safe["outcome"] = outcome
        diagnostics.append(safe)
    return diagnostics


def _stderr_exception_class(stderr: str) -> str | None:
    if not isinstance(stderr, str):
        return None
    allowed = {
        "ModuleNotFoundError", "ImportError", "SyntaxError", "RuntimeError",
        "OSError", "ValueError", "TypeError", "AttributeError", "PermissionError",
        "ConnectError", "ConnectTimeout", "ReadTimeout", "JSONDecodeError",
    }
    for line in reversed(stderr.splitlines()):
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(?::|$)", line)
        if match and match.group(1) in allowed:
            return match.group(1)
    return None


def main() -> int:
    run_id = uuid.uuid4().hex

    def log_event(event: str, **details: object) -> None:
        # Only static classifications and allowlisted primitive fields are passed here.
        _log_event(event, run_id, **details)

    log_event("startup_started")
    try:
        env = _load_env_file(ENV_FILE)
    except Exception as exc:
        log_event("configuration_load_failed", exception=type(exc).__name__)
        return 1
    server_url = env.get(
        "OBSIDIAN_BRIDGE_SERVER_URL", os.environ.get("OBSIDIAN_BRIDGE_SERVER_URL", "")
    ).rstrip("/")
    bridge_key = env.get(
        "OBSIDIAN_BRIDGE_KEY", os.environ.get("OBSIDIAN_BRIDGE_KEY", "")
    )
    vault_path = env.get(
        "OBSIDIAN_VAULT_PATH", os.environ.get("OBSIDIAN_VAULT_PATH", "")
    )
    if not server_url or not bridge_key or not vault_path:
        if _notify("LINE AI Secretary", "Obsidian設定が不足しています。"):
            log_event("notification_shown", purpose="configuration_missing")
        log_event("configuration_missing")
        return 1
    try:
        response = httpx.get(
            server_url + "/api/obsidian/pending",
            headers={"X-Obsidian-Bridge-Key": bridge_key},
            timeout=5.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("pending response must be an object")
    except httpx.HTTPStatusError as exc:
        log_event("pending_check_failed", kind="http_status", status=exc.response.status_code)
        return 1
    except Exception as exc:
        log_event("pending_check_failed", kind="exception", exception=type(exc).__name__)
        return 1
    if payload.get("pending") is not True:
        log_event("pending_none")
        return 0
    try:
        choice, dialog_exit = _ask_execute()
    except Exception as exc:
        log_event("approval_prompt_failed", exception=type(exc).__name__)
        return 1
    if choice is None:
        log_event("approval_prompt_failed", exit_code=dialog_exit)
        return 1
    log_event("notification_shown", purpose="approval_prompt")
    if choice == "later":
        log_event("user_deferred")
        return 0
    log_event("user_approved")
    try:
        subprocess.run(["/usr/bin/open", "-a", "Obsidian"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    bridge_env = _bridge_environment(server_url, bridge_key, vault_path, run_id)
    existing_pythonpath = bridge_env.get("PYTHONPATH", "")
    bridge_env["PYTHONPATH"] = str(REPO_ROOT) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    log_event("bridge_start", executable=Path(sys.executable).name, script=BRIDGE_SCRIPT.name)
    try:
        completed = subprocess.run(
            [sys.executable, str(BRIDGE_SCRIPT)],
            cwd=str(REPO_ROOT),
            env=bridge_env,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        log_event("bridge_process_start_failed", exception=type(exc).__name__)
        log_event("bridge_exit", exit_code=1, classification="process_start_failed")
        if _notify("LINE AI Secretary", "Obsidian保存処理が完了しませんでした。"):
            log_event("notification_shown", purpose="bridge_failed")
        return 1

    diagnostics = _read_bridge_diagnostics(completed.stderr or "", run_id)
    for diagnostic in diagnostics:
        log_event("bridge_diagnostic", **diagnostic)
    if completed.returncode != 0 and not diagnostics:
        log_event(
            "bridge_diagnostic",
            category="bridge_unclassified_failure",
            exception=_stderr_exception_class(completed.stderr or "") or "unknown",
        )
    log_event("bridge_exit", exit_code=completed.returncode)
    if completed.returncode != 0:
        if _notify("LINE AI Secretary", "Obsidian保存処理が完了しませんでした。"):
            log_event("notification_shown", purpose="bridge_failed")
        return completed.returncode
    operation_failed = any(
        diagnostic.get("category") in {
            "vault_write_failed", "local_job_rejected", "local_job_failed"
        }
        or (
            diagnostic.get("category") == "job_completed"
            and diagnostic.get("outcome") == "failure"
        )
        or (
            diagnostic.get("category") == "render_response_invalid"
            and diagnostic.get("operation") == "complete"
        )
        for diagnostic in diagnostics
    )
    if operation_failed:
        log_event("bridge_operation_failed")
        if _notify("LINE AI Secretary", "Obsidian保存処理が完了しませんでした。"):
            log_event("notification_shown", purpose="bridge_failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
