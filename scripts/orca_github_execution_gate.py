"""Unified fail-closed Phase 3-A execution gate.

Pure validation only: this module does not claim tasks, persist replay markers,
dispatch work, or modify the repository. A caller must atomically persist the
returned approval_id as consumed before any worker can execute.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from scripts.orca_github_native_budget_evidence import (
    EvidenceRejected as BudgetEvidenceRejected,
    verify_github_actions_budget,
)

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_MAX_AGE = timedelta(minutes=15)
_APPROVAL_FUTURE_SKEW = timedelta(minutes=2)
_REQUIRED_CYCLE_STAGES = (
    "observed", "diagnosed", "proposed", "tested", "reviewed", "evaluated",
)


class ExecutionGateRejected(ValueError):
    """Raised whenever any execution prerequisite is absent or unverifiable."""


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionGateRejected(f"{field}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ExecutionGateRejected(f"{field}_invalid") from None
    if parsed.tzinfo is None:
        raise ExecutionGateRejected(f"{field}_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _canonical(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    try:
        return json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ExecutionGateRejected("approval_payload_not_canonical") from None


def verify_task_approval(
    approval: Any,
    signing_key: str,
    *,
    repository: str,
    task_id: str,
    request_hash: str,
    now: datetime,
    allowed_approvers: Iterable[str],
) -> str:
    """Verify a short-lived, task-bound approval signed outside the worker."""
    if not isinstance(approval, dict):
        raise ExecutionGateRejected("task_approval_missing")
    if not isinstance(signing_key, str) or len(signing_key.encode("utf-8")) < 32:
        raise ExecutionGateRejected("approval_verification_key_missing")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ExecutionGateRejected("gate_time_timezone_missing")
    if approval.get("schema_version") != 1:
        raise ExecutionGateRejected("approval_schema_invalid")
    if approval.get("repository") != repository:
        raise ExecutionGateRejected("approval_repository_mismatch")
    if approval.get("task_id") != task_id or approval.get("request_hash") != request_hash:
        raise ExecutionGateRejected("approval_task_binding_mismatch")
    approval_id = approval.get("approval_id")
    if not isinstance(approval_id, str) or not _HEX_64.fullmatch(approval_id):
        raise ExecutionGateRejected("approval_id_invalid")
    try:
        approver_allowlist = set(allowed_approvers)
    except (TypeError, ValueError):
        raise ExecutionGateRejected("approver_allowlist_invalid") from None
    if not approver_allowlist or any(not isinstance(value, str) or not value for value in approver_allowlist):
        raise ExecutionGateRejected("approver_allowlist_invalid")
    approver = approval.get("approved_by")
    if not isinstance(approver, str) or approver not in approver_allowlist:
        raise ExecutionGateRejected("approver_not_allowed")
    if approval.get("decision") != "approve":
        raise ExecutionGateRejected("approval_decision_not_approve")
    signature = approval.get("signature")
    if not isinstance(signature, str) or not _HEX_64.fullmatch(signature):
        raise ExecutionGateRejected("approval_signature_missing_or_invalid")
    expected = hmac.new(
        signing_key.encode("utf-8"), _canonical(approval), hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ExecutionGateRejected("approval_signature_invalid")

    current = now.astimezone(timezone.utc)
    approved_at = _timestamp(approval.get("approved_at"), "approval_timestamp")
    expires_at = _timestamp(approval.get("expires_at"), "approval_expiry")
    if approved_at > current + _APPROVAL_FUTURE_SKEW:
        raise ExecutionGateRejected("approval_timestamp_in_future")
    if current - approved_at > _APPROVAL_MAX_AGE:
        raise ExecutionGateRejected("approval_expired")
    if expires_at <= current or expires_at <= approved_at:
        raise ExecutionGateRejected("approval_expired")
    if expires_at - approved_at > _APPROVAL_MAX_AGE:
        raise ExecutionGateRejected("approval_lifetime_too_long")
    return approval_id


def _validate_cycle_candidate(cycle: Any) -> None:
    if not isinstance(cycle, dict) or cycle.get("schema_version") != 1:
        raise ExecutionGateRejected("improvement_cycle_missing_or_invalid")
    if cycle.get("stage") != "evaluated" or cycle.get("decision") != "accepted_candidate":
        raise ExecutionGateRejected("improvement_candidate_not_accepted")
    for flag in ("execution_authorized", "auto_apply", "auto_merge", "auto_deploy"):
        if cycle.get(flag) is not False:
            raise ExecutionGateRejected("unsafe_improvement_execution_flag")
    evidence = cycle.get("evidence")
    if not isinstance(evidence, dict):
        raise ExecutionGateRejected("improvement_evidence_missing")
    for stage in _REQUIRED_CYCLE_STAGES:
        refs = evidence.get(stage)
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, str) or not ref.strip() for ref in refs
        ):
            raise ExecutionGateRejected("improvement_stage_evidence_missing")
    details = cycle.get("details")
    evaluation = details.get("evaluation") if isinstance(details, dict) else None
    if not isinstance(evaluation, dict):
        raise ExecutionGateRejected("improvement_evaluation_missing")
    if evaluation.get("tests_passed") is not True or evaluation.get("critic_verdict") != "pass":
        raise ExecutionGateRejected("improvement_validation_not_passed")
    baseline = evaluation.get("baseline_metric")
    candidate = evaluation.get("candidate_metric")
    if (isinstance(baseline, bool) or not isinstance(baseline, (int, float))
            or isinstance(candidate, bool) or not isinstance(candidate, (int, float))
            or not math.isfinite(baseline) or not math.isfinite(candidate)
            or candidate <= baseline):
        raise ExecutionGateRejected("improvement_metric_not_positive")
    cycle_id = cycle.get("cycle_id")
    if not isinstance(cycle_id, str) or not _HEX_64.fullmatch(cycle_id):
        raise ExecutionGateRejected("improvement_cycle_identity_invalid")


def evaluate_execution_gate(
    *,
    repository: str,
    queue_state: Any,
    task_id: str,
    request_hash: str,
    approval: Any,
    approval_signing_key: str,
    allowed_approvers: Iterable[str],
    consumed_approval_ids: Any,
    budget_evidence: Any,
    budget_signing_key: str,
    billing_account_id: str,
    improvement_cycle: Any,
    now: datetime,
) -> dict[str, Any]:
    """Return PASS for exactly one queued task, otherwise fail closed.

    PASS is permission to proceed only after the caller atomically records
    consume_approval_id in the durable state. This function never executes work.
    """
    if not isinstance(repository, str) or "/" not in repository:
        raise ExecutionGateRejected("repository_invalid")
    if not isinstance(queue_state, dict):
        raise ExecutionGateRejected("queue_state_missing_or_invalid")
    if queue_state.get("schema_version") != 1:
        raise ExecutionGateRejected("queue_schema_invalid")
    revision = queue_state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ExecutionGateRejected("queue_revision_invalid")
    if queue_state.get("emergency_stop") is not False:
        raise ExecutionGateRejected("emergency_stop_active_or_unverifiable")
    if queue_state.get("global_hold") is not False:
        raise ExecutionGateRejected("global_hold_active_or_unverifiable")
    tasks = queue_state.get("tasks")
    if (not isinstance(tasks, list) or "active_lease" not in queue_state
            or "consumed_approval_ids" not in queue_state):
        raise ExecutionGateRejected("queue_tasks_or_lease_missing")
    seen_task_ids = set()
    for row in tasks:
        if not isinstance(row, dict):
            raise ExecutionGateRejected("queue_task_invalid")
        row_id = row.get("task_id")
        row_hash = row.get("request_hash")
        if not isinstance(row_id, str) or not row_id or row_id in seen_task_ids:
            raise ExecutionGateRejected("queue_task_identity_invalid")
        if not isinstance(row_hash, str) or not _HEX_64.fullmatch(row_hash):
            raise ExecutionGateRejected("queue_task_request_hash_invalid")
        if row.get("status") not in {"queued", "claimed", "done", "failed"}:
            raise ExecutionGateRejected("queue_task_status_invalid")
        seen_task_ids.add(row_id)
    lease = queue_state.get("active_lease")
    if lease is not None:
        raise ExecutionGateRejected("active_lease_present")
    claimed = [task for task in tasks if isinstance(task, dict) and task.get("status") == "claimed"]
    if claimed:
        raise ExecutionGateRejected("claimed_task_present")
    matches = [
        task for task in tasks
        if isinstance(task, dict) and task.get("task_id") == task_id
    ]
    if len(matches) != 1:
        raise ExecutionGateRejected("task_identity_missing_or_ambiguous")
    task = matches[0]
    if task.get("status") != "queued":
        raise ExecutionGateRejected("task_not_queued")
    if task.get("request_hash") != request_hash or not isinstance(request_hash, str) or not _HEX_64.fullmatch(request_hash):
        raise ExecutionGateRejected("task_request_hash_mismatch")

    persisted_ledger = queue_state.get("consumed_approval_ids")
    if (not isinstance(persisted_ledger, list)
            or any(not isinstance(value, str) or not _HEX_64.fullmatch(value)
                   for value in persisted_ledger)
            or len(persisted_ledger) != len(set(persisted_ledger))):
        raise ExecutionGateRejected("approval_replay_ledger_missing_or_invalid")
    if consumed_approval_ids != persisted_ledger:
        raise ExecutionGateRejected("approval_replay_ledger_snapshot_mismatch")
    consumed_approval_ids = persisted_ledger
    approval_id = verify_task_approval(
        approval, approval_signing_key, repository=repository,
        task_id=task_id, request_hash=request_hash, now=now,
        allowed_approvers=allowed_approvers,
    )
    if approval_id in consumed_approval_ids:
        raise ExecutionGateRejected("approval_replay_detected")

    try:
        budget = verify_github_actions_budget(
            budget_evidence, budget_signing_key, now,
            expected_repository=repository,
            expected_billing_account_id=billing_account_id,
            min_remaining_minutes=45,
        )
    except BudgetEvidenceRejected as exc:
        raise ExecutionGateRejected(f"budget_gate_blocked:{exc}") from None
    if budget.get("status") not in {"PASS", "WARN"}:
        raise ExecutionGateRejected("budget_gate_not_passed")

    _validate_cycle_candidate(improvement_cycle)
    return {
        "status": "PASS",
        "execution_enabled": False,
        "task_id": task_id,
        "queue_revision": revision,
        "consume_approval_id": approval_id,
        "budget_status": budget["status"],
        "improvement_cycle_id": improvement_cycle["cycle_id"],
        "max_tasks_per_run": 1,
        "required_next_action": "persist_approval_replay_marker_before_worker_claim",
    }
