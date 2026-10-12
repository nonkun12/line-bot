"""Bridge sanitized distributed-loop results into deterministic Recovery AI.

The optional Apple advisor is called only after a failure is durably recorded and
read back. It adds text-only diagnostics; it never changes the deterministic
decision or the loop's exit status. Hosted Actions keep the opt-in disabled.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.recovery_ai import RecoveryStateError, RecoveryStore


def _category(result: dict[str, Any]) -> str:
    reason = str(result.get("failure_reason", "")).lower()
    status = str(result.get("status", "")).upper()
    # Storage failures must stop closed, not be retried as ordinary unknown errors.
    if any(token in reason for token in (
        "vault_write_failed", "permissionerror", "permission_denied",
        "state_persistence_failure", "recovery state persistence failed",
    )):
        return "state_persistence_failure"
    # Prefer specific transient categories before broader timeout/crash checks.
    if any(token in reason for token in (
        "rate_limited", "rate_limit", "too_many_requests", "http_429", "status_429",
    )):
        return "rate_limited"
    if any(token in reason for token in (
        "service_unavailable", "temporarily_unavailable", "http_503", "status_503",
    )):
        return "service_unavailable"
    if any(token in reason for token in (
        "network_transient", "connection_reset", "connection_refused",
        "connection_error", "dns_failure", "network_unreachable",
    )):
        return "network_transient"
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


def _optional_local_advice(task_id: str, category: str) -> dict[str, Any]:
    """Call fm only on explicit local opt-in; return advisory metadata, never control."""
    if os.environ.get("RECOVERY_AI_APPLE_ADVISOR") != "1":
        return {"available": False, "reason": "advisor_not_enabled"}
    if category == "state_persistence_failure":
        return {"available": False, "reason": "state_persistence_failure"}
    try:
        from scripts.apple_foundation_models_advisor import advise
        result = advise(task_id, category)
        return {"available": result.available, "advice": result.advice, "reason": result.reason}
    except Exception:
        # The optional model must never change the deterministic decision or halt policy.
        return {"available": False, "reason": "advisor_unexpected_error"}


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
    verified_success = (
        result.get("exit_code") == 0
        and (
            (status == "PASS" and not result.get("failure_reason"))
            or (status == "NO_CHANGE" and result.get("failure_reason") in {"", "no_change"})
        )
    )
    if verified_success:
        store.record_success(task_id, verified=True)
        return {"recorded": True, "status": status, "verified": True}

    category = _category(result)
    decision = store.record_failure(task_id, category, ())
    persisted = store.task_status(task_id)
    if (
        persisted.get("last_category") != category
        or persisted.get("last_fingerprint") != decision.fingerprint
        or persisted.get("consecutive_failures") != decision.consecutive_failures
    ):
        raise RecoveryStateError("recovery state read-back verification failed")
    output = {"recorded": True, "status": status, "decision": asdict(decision)}
    # Keep the hot path fast: bounded transient retries need no model advice.
    # Invoke the optional local model only when a repair or safety hold needs diagnosis.
    # Advisory is deliberately last: durable deterministic state is the gate.
    if decision.action in {"REPAIR_ONCE", "HOLD", "STOP_FAIL_CLOSED"}:
        output["apple_advisor"] = _optional_local_advice(task_id, category)
    else:
        output["apple_advisor"] = {"available": False, "reason": "fast_path_no_advice_needed"}
    return output
