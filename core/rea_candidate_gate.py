"""Fail-closed gate for publishing a single task result to an isolated REA candidate ref."""
from __future__ import annotations

import re
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")


def _blocked(reason: str) -> dict[str, Any]:
    return {"allowed": False, "status": "BLOCKED", "reason_code": reason}


def validate_candidate_publication(
    rows: object,
    queue_data: object,
    catalog_data: object,
    *,
    expected_base_sha: str,
    observed_head_sha: str,
    changed_paths: object,
) -> dict[str, Any]:
    """Allow candidate-only publication after a task-bound approval and safe REA HOLD.

    This gate does not promote to line-dev/main and grants no merge/deploy authority.
    """
    if (
        not isinstance(expected_base_sha, str) or not _SHA.fullmatch(expected_base_sha)
        or not isinstance(observed_head_sha, str) or not _SHA.fullmatch(observed_head_sha)
    ):
        return _blocked("commit_identity_invalid")
    if expected_base_sha == observed_head_sha:
        return _blocked("candidate_has_no_commit")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return _blocked("candidate_requires_exactly_one_task")
    row = rows[0]
    task_id = row.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        return _blocked("candidate_task_id_invalid")
    if (
        row.get("status") != "BLOCKED"
        or type(row.get("exit_code")) is not int or row.get("exit_code") != 1
        or row.get("failure_reason") != "rea_artifact_hold"
        or row.get("base_sha") != expected_base_sha
        or row.get("produced_sha") != observed_head_sha
    ):
        return _blocked("candidate_not_blocked_only_by_independent_verification")
    rea = row.get("rea_artifact")
    if not isinstance(rea, dict):
        return _blocked("candidate_rea_evidence_missing")
    if (
        rea.get("status") != "HOLD"
        or rea.get("reason_code") != "verification_incomplete"
        or not isinstance(rea.get("tests"), str) or rea.get("tests") not in {"UNKNOWN", "NOT_RUN"}
        or not isinstance(rea.get("risk"), str) or rea.get("risk") not in {"LOW", "MEDIUM"}
        or rea.get("diff_scan") != "PASS"
        or rea.get("stop_state") != "INACTIVE"
        or rea.get("hold_state") != "CLEAR"
        or type(rea.get("changed_file_count")) is not int
        or rea.get("changed_file_count") < 1
    ):
        return _blocked("candidate_rea_conditions_not_met")
    if any(rea.get(key) is not False for key in (
        "execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized"
    )):
        return _blocked("candidate_rea_authority_violation")

    approval = row.get("execution_approval")
    if not isinstance(approval, dict):
        return _blocked("candidate_execution_approval_missing")
    consumption = approval.get("consumption")
    if (
        approval.get("gate") != "PASS"
        or approval.get("execution_authorized") is not True
        or approval.get("scope") != "execution"
        or approval.get("actor") != "nonkun12"
        or approval.get("task_id") != task_id
        or approval.get("base_sha") != expected_base_sha
        or not isinstance(approval.get("instruction_sha256"), str)
        or not _HEX64.fullmatch(approval["instruction_sha256"])
        or not isinstance(approval.get("allowed_paths_sha256"), str)
        or not _HEX64.fullmatch(approval["allowed_paths_sha256"])
        or not isinstance(consumption, dict)
        or consumption.get("gate") != "PASS"
        or consumption.get("reason_code") != "approval_consumed_once"
        or consumption.get("marker_sha") != expected_base_sha
        or not isinstance(consumption.get("marker_ref"), str)
        or not re.fullmatch(r"refs/heads/rsi-approval-consumed/[0-9a-f]{64}", consumption["marker_ref"])
    ):
        return _blocked("candidate_execution_approval_invalid")

    queued = queue_data.get("tasks") if isinstance(queue_data, dict) else None
    registered = catalog_data.get("tasks") if isinstance(catalog_data, dict) else None
    if not isinstance(queued, list) or not isinstance(registered, list):
        return _blocked("candidate_task_registry_missing")
    queued_matches = [item for item in queued if isinstance(item, dict) and item.get("id") == task_id]
    registered_matches = [item for item in registered if isinstance(item, dict) and item.get("id") == task_id]
    if len(queued_matches) != 1 or len(registered_matches) != 1:
        return _blocked("candidate_task_registry_identity_invalid")
    queue_task, catalog_task = queued_matches[0], registered_matches[0]
    allowed = catalog_task.get("allowed_paths")
    if (
        catalog_task.get("execution_approved") is not True
        or queue_task.get("instruction") != catalog_task.get("instruction")
        or queue_task.get("allowed_paths") != allowed
        or not isinstance(allowed, list) or not allowed
        or any(
            not isinstance(path, str) or not path or path != path.strip()
            or path.startswith("/") or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            for path in allowed
        )
        or len(set(allowed)) != len(allowed)
    ):
        return _blocked("candidate_task_definition_not_approved")

    if (
        not isinstance(changed_paths, list) or not changed_paths
        or any(not isinstance(path, str) or not path for path in changed_paths)
        or len(set(changed_paths)) != len(changed_paths)
        or not set(changed_paths).issubset(set(allowed))
        or len(changed_paths) != rea["changed_file_count"]
    ):
        return _blocked("candidate_changed_paths_outside_allowlist")
    return {
        "allowed": True,
        "status": "PASS",
        "reason_code": "isolated_candidate_eligible",
        "task_id": task_id,
        "base_sha": expected_base_sha,
        "produced_sha": observed_head_sha,
        "changed_file_count": len(changed_paths),
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }


__all__ = ["validate_candidate_publication"]
