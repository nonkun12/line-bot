"""Single fail-closed orchestration contract for the distributed Control Tower.

This module unifies outcome classification across the loop, Recovery AI, and
post-run observation. It is deliberately a policy/state-machine layer: it does
not execute model-generated commands, apply patches, clear HOLD, merge, or deploy.
"""
from __future__ import annotations

import re
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
_ALLOWED_STATUSES = frozenset({
    "PASS", "NO_CHANGE", "FAIL", "TIMEOUT", "STOPPED", "BLOCKED", "NOT_RUN",
})
_RECOVERY_ACTIONS = frozenset({
    "RETRY", "REPAIR_ONCE", "HOLD", "STOP_FAIL_CLOSED",
})


def coordinate_outcome(result: object) -> dict[str, Any]:
    """Return one authoritative next-step decision from sanitized run evidence.

    A success is accepted only when the task exit code, per-run identity, and
    durable Recovery AI verification all agree. Any malformed or incomplete
    evidence stops the loop. Failure actions are recommendations only; no retry
    or repair is claimed to have run here.
    """
    if not isinstance(result, dict):
        return _decision("STOP", "STOP_AND_REPORT", "invalid_outcome", False)

    task_id = result.get("task_id")
    status = result.get("status")
    exit_code = result.get("exit_code")
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 100:
        return _decision("STOP", "STOP_AND_REPORT", "invalid_task_identity", False)
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        return _decision("STOP", "STOP_AND_REPORT", "invalid_status", False)

    if status in {"BLOCKED", "STOPPED", "NOT_RUN"}:
        return _decision("STOP", "REPORT_BLOCKED", "execution_not_completed", False)

    recovery = result.get("recovery_ai")
    if not isinstance(recovery, dict) or recovery.get("recorded") is not True:
        return _decision("STOP", "STOP_AND_REPORT", "recovery_evidence_missing", False)

    if status in {"PASS", "NO_CHANGE"}:
        base_sha = result.get("base_sha")
        produced_sha = result.get("produced_sha")
        run_nonce = result.get("run_nonce")
        if type(exit_code) is not int or exit_code != 0:
            return _decision("STOP", "STOP_AND_REPORT", "success_exit_code_invalid", False)
        if (
            not isinstance(base_sha, str) or not _SHA_RE.fullmatch(base_sha)
            or not isinstance(produced_sha, str) or not _SHA_RE.fullmatch(produced_sha)
            or not isinstance(run_nonce, str) or not _NONCE_RE.fullmatch(run_nonce)
        ):
            return _decision("STOP", "STOP_AND_REPORT", "run_identity_invalid", False)
        if status == "NO_CHANGE" and base_sha != produced_sha:
            return _decision("STOP", "STOP_AND_REPORT", "no_change_sha_mismatch", False)
        if recovery.get("verified") is not True or recovery.get("status") != status:
            return _decision("STOP", "STOP_AND_REPORT", "recovery_verification_mismatch", False)
        expected_evidence = {
            "task_id": task_id,
            "base_sha": base_sha,
            "produced_sha": produced_sha,
            "run_nonce": run_nonce,
        }
        if recovery.get("evidence") != expected_evidence:
            return _decision("STOP", "STOP_AND_REPORT", "recovery_run_evidence_mismatch", False)
        observation = result.get("control_tower")
        observation_ok = isinstance(observation, dict) and observation.get("recorded") is True
        if not observation_ok:
            return _decision(
                "STOP", "STOP_AND_REPORT", "control_tower_observation_missing", False, task_id
            )
        return {
            "phase": "REPORT",
            "next_action": "REPORT_VERIFIED_SUCCESS",
            "reason_code": "verified_success",
            "allow_continue": True,
            "task_id": task_id,
            "observation_degraded": False,
            "repair_executed": False,
        }

    recovery_decision = recovery.get("decision")
    action = recovery_decision.get("action") if isinstance(recovery_decision, dict) else None
    if action not in _RECOVERY_ACTIONS:
        return _decision("STOP", "HOLD_FOR_REVIEW", "recovery_action_missing_or_unknown", False)
    if action == "REPAIR_ONCE":
        return {
            "phase": "DIAGNOSE",
            "next_action": "PREPARE_BOUNDED_REPAIR_REVIEW",
            "reason_code": "recovery_authorized_one_repair_attempt",
            "allow_continue": False,
            "task_id": task_id,
            "repair_executed": False,
            "requires_repair_verification": True,
        }
    if action == "RETRY":
        return {
            "phase": "RECOVER",
            "next_action": "SCHEDULE_BOUNDED_RETRY",
            "reason_code": "recovery_authorized_bounded_retry",
            "allow_continue": False,
            "task_id": task_id,
            "retry_executed": False,
        }
    if action == "STOP_FAIL_CLOSED":
        return _decision("STOP", "STOP_AND_REPORT", "recovery_state_unavailable", False, task_id)
    return _decision("STOP", "HOLD_FOR_REVIEW", "recovery_ai_requires_hold", False, task_id)


def _decision(
    phase: str,
    next_action: str,
    reason_code: str,
    allow_continue: bool,
    task_id: str | None = None,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "next_action": next_action,
        "reason_code": reason_code,
        "allow_continue": allow_continue,
        "task_id": task_id,
        "repair_executed": False,
    }


__all__ = ["coordinate_outcome"]
