"""Deterministic, non-authoritative REA evaluation of completed task evidence.

This module evaluates evidence supplied by a runner; it does not execute code,
inspect repositories, approve patches, clear holds, or authorize merge/deploy.
Missing or contradictory evidence fails closed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

_ALLOWED_TEST = {"PASS", "FAIL", "NOT_RUN", "UNKNOWN"}
_ALLOWED_SCAN = {"PASS", "FAIL", "NOT_RUN", "UNKNOWN"}
_ALLOWED_RISK = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}


def _result(status: str, reason: str, evidence_sha256: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason,
        "evidence_sha256": evidence_sha256,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
        "mode": "REA_EVIDENCE_ONLY",
    }


def evaluate_artifact_evidence(evidence: object) -> dict[str, Any]:
    """Classify task-result evidence without granting any execution authority.

    Required keys: task_id, base_sha, head_sha, changed_files, tests,
    diff_scan, risk, stop_state, hold_state. Tests and diff_scan are PASS/FAIL/
    NOT_RUN/UNKNOWN. STOP must be INACTIVE and HOLD must be CLEAR.
    """
    if not isinstance(evidence, dict):
        return _result("HOLD", "evidence_not_object")

    try:
        canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return _result("HOLD", "evidence_not_serializable")

    required = {
        "task_id", "base_sha", "head_sha", "changed_files", "tests",
        "diff_scan", "risk", "stop_state", "hold_state",
    }
    if not required.issubset(evidence):
        return _result("HOLD", "required_evidence_missing", evidence_hash)

    if evidence["stop_state"] != "INACTIVE":
        return _result("BLOCKED", "stop_active_or_unverified", evidence_hash)
    if evidence["hold_state"] != "CLEAR":
        return _result("BLOCKED", "hold_active_or_unverified", evidence_hash)

    task_id = evidence["task_id"]
    base_sha, head_sha = evidence["base_sha"], evidence["head_sha"]
    changed_files = evidence["changed_files"]
    tests, diff_scan, risk = evidence["tests"], evidence["diff_scan"], evidence["risk"]

    if not isinstance(task_id, str) or not task_id.strip():
        return _result("HOLD", "task_identity_missing", evidence_hash)
    if not all(isinstance(x, str) and len(x) == 40 and all(c in "0123456789abcdef" for c in x.lower()) for x in (base_sha, head_sha)):
        return _result("HOLD", "commit_identity_invalid", evidence_hash)
    if not isinstance(changed_files, list) or any(not isinstance(x, str) or not x.strip() for x in changed_files):
        return _result("HOLD", "changed_files_evidence_invalid", evidence_hash)
    if tests not in _ALLOWED_TEST or diff_scan not in _ALLOWED_SCAN or risk not in _ALLOWED_RISK:
        return _result("HOLD", "evidence_value_invalid", evidence_hash)

    if risk in {"HIGH", "UNKNOWN"}:
        return _result("BLOCKED" if risk == "HIGH" else "HOLD", "risk_" + risk.lower(), evidence_hash)
    if tests == "FAIL" or diff_scan == "FAIL":
        return _result("FAIL", "verification_failed", evidence_hash)
    if tests != "PASS" or diff_scan != "PASS":
        return _result("HOLD", "verification_incomplete", evidence_hash)
    if base_sha == head_sha and not changed_files:
        return _result("NO_CHANGE", "no_artifact_change", evidence_hash)
    if base_sha == head_sha:
        return _result("HOLD", "changed_files_without_new_commit", evidence_hash)
    if not changed_files:
        return _result("HOLD", "commit_changed_without_file_evidence", evidence_hash)

    return _result("PASS", "artifact_evidence_verified", evidence_hash)


__all__ = ["evaluate_artifact_evidence"]
