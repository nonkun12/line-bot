"""Bridge sanitized distributed-loop results into deterministic Recovery AI.

This adapter records decisions only. It never reruns tasks, applies patches, or
changes the existing loop's fail-closed stop behavior.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re
from typing import Any

from scripts.recovery_ai import RecoveryStore


def _category(result: dict[str, Any]) -> str:
    reason = str(result.get("failure_reason", "")).lower()
    status = str(result.get("status", "")).upper()
    if status == "TIMEOUT" or "timeout" in reason:
        return "timeout"
    if any(token in reason for token in ("sha_mismatch", "nonce_mismatch", "outside_allowed_paths", "security")):
        return "security_violation"
    if any(token in reason for token in ("evidence", "summary_missing", "summary_invalid")):
        return "invalid_evidence"
    if status == "FAIL" and any(token in reason for token in ("pytest", "test_regression")):
        return "test_regression"
    if any(token in reason for token in ("crash", "process")):
        return "process_crash"
    return "unknown"


def _has_verified_run_identity(result: dict[str, Any], status: str) -> bool:
    """Require fresh per-run identifiers before a success can reset failure state."""
    base_sha = str(result.get("base_sha", "")).lower()
    produced_sha = str(result.get("produced_sha", "")).lower()
    run_nonce = str(result.get("run_nonce", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        return False
    if not re.fullmatch(r"[0-9a-f]{40}", produced_sha):
        return False
    if not re.fullmatch(r"[0-9a-f]{32}", run_nonce):
        return False
    if status == "NO_CHANGE" and base_sha != produced_sha:
        return False
    return True


def record_loop_outcome(state_path: str | Path, result: dict[str, Any]) -> dict[str, Any]:
    """Persist one verified outcome; fail closed if state cannot be trusted."""
    if not isinstance(result, dict):
        raise ValueError("loop result must be an object")
    task_id = str(result.get("task_id", "")).strip()
    if not task_id:
        # Synthetic queue/incident summaries are not task outcomes.
        return {"recorded": False, "reason": "no_task_id"}
    store = RecoveryStore(state_path)
    status = str(result.get("status", "")).upper()
    run_identity_verified = _has_verified_run_identity(result, status)
    success_like = status in {"PASS", "NO_CHANGE"}
    if success_like and (result.get("exit_code") != 0 or not run_identity_verified):
        decision = store.record_failure(task_id, "invalid_evidence", ())
        return {"recorded": True, "status": status, "decision": asdict(decision)}

    verified_success = (
        result.get("exit_code") == 0
        and run_identity_verified
        and (
            (status == "PASS" and not result.get("failure_reason"))
            or (status == "NO_CHANGE" and result.get("failure_reason") in {"", "no_change"})
        )
    )
    if verified_success:
        store.record_success(task_id, verified=True)
        return {"recorded": True, "status": status, "verified": True}
    decision = store.record_failure(task_id, _category(result), ())
    return {"recorded": True, "status": status, "decision": asdict(decision)}
