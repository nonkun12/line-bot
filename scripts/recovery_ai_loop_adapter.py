"""Bridge sanitized distributed-loop results into deterministic Recovery AI.

This adapter records decisions only. It never reruns tasks, applies patches, or
changes the existing loop's fail-closed stop behavior. Optional RAG history is
advisory only: it never changes Recovery AI decisions.
"""
from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import re
from typing import Any

from scripts.recovery_ai import RecoveryStore, failure_fingerprint


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
    base_sha = str(result.get("base_sha", ""))
    produced_sha = str(result.get("produced_sha", ""))
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


def _attach_rag_advisory(
    outcome: dict[str, Any], *, task_id: str, status: str, category: str
) -> dict[str, Any]:
    """Record/search sanitized RAG history when configured; never affect the decision."""
    db_path = os.environ.get("RECOVERY_RAG_DB_PATH", "").strip()
    if not db_path:
        return outcome
    namespace = os.environ.get("RECOVERY_RAG_NAMESPACE", "distributed-loop").strip()
    if not namespace:
        outcome["recovery_rag"] = {"recorded": False, "error": "invalid_namespace"}
        return outcome
    try:
        from scripts.recovery_rag import record_outcome, search_prior_outcomes

        fingerprint = failure_fingerprint(task_id, category, ())
        # Read only a small, sanitized summary. Retrieved text is never executed
        # or passed to the repair path as instructions.
        prior = search_prior_outcomes(
            db_path, namespace=namespace, query=category, limit=5
        )
        record_outcome(
            db_path,
            namespace=namespace,
            task_id=task_id,
            status=status if status in {"PASS", "NO_CHANGE", "FAIL", "TIMEOUT", "STOPPED", "BLOCKED"} else "BLOCKED",
            category=category,
            fingerprint=fingerprint,
        )
        outcome["recovery_rag"] = {
            "recorded": True,
            "prior_matches": len(prior),
            "prior_statuses": sorted({
                item.get("metadata", {}).get("status", "")
                for item in prior
                if item.get("metadata", {}).get("status")
            }),
            "scope": "current_database",
        }
    except Exception as exc:
        # RAG is non-authoritative. Preserve the already-persisted Recovery AI
        # decision and expose only the exception class, never its raw message.
        outcome["recovery_rag"] = {
            "recorded": False,
            "error": type(exc).__name__,
        }
    return outcome


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
    failure_reason = str(result.get("failure_reason", "")).strip().lower()
    # A preflight authorization denial or launch-time HEAD race means no task
    # actually ran. Record it in the loop report, but do not count it as a task
    # failure or trip Recovery AI's repeated-failure HOLD circuit breaker.
    if status == "BLOCKED" and (
        failure_reason.startswith("control_tower_gate:")
        or failure_reason == "control_tower_head_changed"
    ):
        return {
            "recorded": False,
            "reason": "preflight_blocked_not_task_failure",
        }
    run_identity_verified = _has_verified_run_identity(result, status)
    success_like = status in {"PASS", "NO_CHANGE"}
    if success_like and (type(result.get("exit_code")) is not int or result.get("exit_code") != 0 or not run_identity_verified):
        decision = store.record_failure(task_id, "invalid_evidence", ())
        # Invalid run identity must invalidate the task result itself; logging a
        # HOLD decision while leaving status=PASS could falsely complete a task.
        result["status"] = "FAIL"
        result["exit_code"] = 1
        result["failure_reason"] = "recovery_ai_invalid_evidence"
        outcome = {"recorded": True, "status": "FAIL", "decision": asdict(decision)}
        return _attach_rag_advisory(
            outcome, task_id=task_id, status="FAIL", category="invalid_evidence"
        )

    verified_success = (
        type(result.get("exit_code")) is int
        and result.get("exit_code") == 0
        and run_identity_verified
        and (
            (status == "PASS" and not result.get("failure_reason"))
            or (status == "NO_CHANGE" and result.get("failure_reason") in {"", "no_change"})
        )
    )
    if verified_success:
        evidence = {
            "task_id": task_id,
            "base_sha": result["base_sha"],
            "produced_sha": result["produced_sha"],
            "run_nonce": result["run_nonce"],
        }
        store.record_success(task_id, verified=True, evidence=evidence)
        persisted = store.task_status(task_id).get("last_success_evidence")
        if persisted != evidence:
            raise RuntimeError("recovery_ai_persisted_evidence_mismatch")
        return _attach_rag_advisory(
            {"recorded": True, "status": status, "verified": True, "evidence": persisted},
            task_id=task_id, status=status, category="unknown",
        )
    category = _category(result)
    decision = store.record_failure(task_id, category, ())
    return _attach_rag_advisory(
        {"recorded": True, "status": status, "decision": asdict(decision)},
        task_id=task_id, status=status, category=category,
    )
