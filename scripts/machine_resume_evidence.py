"""Strict, task-bound machine evidence policy for autonomous resume eligibility.

This module is a pure validator. It never edits Recovery AI state, clears HOLD,
dispatches work, applies patches, merges, or deploys. A trusted workflow must
create the evidence in the same run and supply its run identity independently.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_REQUIRED_FIELDS = frozenset({
    "schema_version", "task_id", "instruction_sha256", "allowed_paths_sha256",
    "base_sha", "target_sha", "evaluated_paths", "scanner_complete",
    "scanner_status", "tests_status", "tests_exit_code", "cause_status",
    "cause_evidence_sha256", "workflow_run_id", "run_attempt", "created_at",
    "nonce",
})


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA64.fullmatch(value) is not None


def _canonical_paths(value: Any) -> tuple[list[str], str] | None:
    if (
        not isinstance(value, list) or not value or len(value) > 20
        or not all(isinstance(item, str) and item and len(item) <= 240 for item in value)
        or len(set(value)) != len(value)
    ):
        return None
    for path in value:
        if (
            path.startswith("/") or "\\" in path or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(char in path for char in "*?[]{}")
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            return None
    paths = sorted(value)
    digest = hashlib.sha256(
        json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return paths, digest


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "eligible": False, "reason_code": reason}


def validate_machine_resume_evidence(
    task: object,
    evidence: object,
    *,
    expected_base_sha: str,
    expected_workflow_run_id: str,
    expected_run_attempt: int,
    expected_nonce: str,
    now: datetime | None = None,
    max_age_seconds: int = 3600,
) -> dict[str, Any]:
    """Validate a machine-review contract and one fresh, same-run REA receipt.

    The caller must independently obtain expected_workflow_run_id and
    expected_run_attempt from the currently executing trusted workflow context.
    This function validates claims; it does not authenticate an untrusted artifact.
    """
    if (
        not isinstance(expected_base_sha, str) or not _SHA40.fullmatch(expected_base_sha)
        or not isinstance(expected_workflow_run_id, str)
        or not expected_workflow_run_id.isdigit()
        or type(expected_run_attempt) is not int or expected_run_attempt < 1
        or not isinstance(expected_nonce, str) or not _NONCE.fullmatch(expected_nonce)
        or type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400
    ):
        return _blocked("resume_expected_context_invalid")
    if not isinstance(task, dict):
        return _blocked("resume_task_invalid")
    task_id = task.get("id")
    instruction = task.get("instruction")
    paths = _canonical_paths(task.get("allowed_paths"))
    if (
        not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id)
        or not isinstance(instruction, str) or not instruction.strip()
        or paths is None
        or task.get("execution_approved") is not True
        or task.get("resume_policy") != "machine_evidence"
    ):
        return _blocked("resume_task_contract_invalid")
    lowered = instruction.casefold()
    if any(term in lowered for term in (
        "人手レビュー", "人間のレビュー", "human review", "manual review",
        "after human", "after manual",
    )):
        return _blocked("resume_task_requires_human_review")
    if not isinstance(evidence, dict) or set(evidence) != _REQUIRED_FIELDS:
        return _blocked("resume_evidence_schema_invalid")

    instruction_sha = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    if (
        evidence.get("schema_version") != 1
        or evidence.get("task_id") != task_id
        or evidence.get("instruction_sha256") != instruction_sha
        or evidence.get("allowed_paths_sha256") != paths[1]
        or evidence.get("base_sha") != expected_base_sha
        or not isinstance(evidence.get("target_sha"), str)
        or not _SHA40.fullmatch(evidence["target_sha"])
        or evidence.get("evaluated_paths") != paths[0]
        or evidence.get("scanner_complete") is not True
        or evidence.get("scanner_status") != "PASS"
        or evidence.get("tests_status") != "PASS"
        or type(evidence.get("tests_exit_code")) is not int
        or evidence.get("tests_exit_code") != 0
        or evidence.get("cause_status") != "FIXED"
        or not _digest(evidence.get("cause_evidence_sha256"))
        or evidence.get("workflow_run_id") != expected_workflow_run_id
        or type(evidence.get("run_attempt")) is not int
        or evidence.get("run_attempt") != expected_run_attempt
        or not isinstance(evidence.get("nonce"), str)
        or not _NONCE.fullmatch(evidence["nonce"])
        or evidence.get("nonce") != expected_nonce
    ):
        return _blocked("resume_evidence_binding_or_gate_failed")

    created_at = evidence.get("created_at")
    if not isinstance(created_at, str) or len(created_at) > 64:
        return _blocked("resume_evidence_timestamp_invalid")
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return _blocked("resume_evidence_timestamp_invalid")
    if timestamp.tzinfo is None:
        return _blocked("resume_evidence_timestamp_timezone_missing")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return _blocked("resume_validator_clock_timezone_missing")
    age = (current - timestamp).total_seconds()
    if age < -60 or age > max_age_seconds:
        return _blocked("resume_evidence_stale_or_future")

    return {
        "status": "PASS",
        "eligible": True,
        "reason_code": "task_bound_machine_rea_evidence_valid",
        "task_id": task_id,
        "base_sha": expected_base_sha,
        "target_sha": evidence["target_sha"],
        "evaluated_paths": paths[0],
        "workflow_run_id": expected_workflow_run_id,
        "run_attempt": expected_run_attempt,
        "nonce": evidence["nonce"],
    }


__all__ = ["validate_machine_resume_evidence"]
