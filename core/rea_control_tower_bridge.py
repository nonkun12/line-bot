"""Map validated REA review-candidate output to a safe Control Tower decision.

Pure, advisory-only bridge. It never selects a task or grants mutation rights.
Malformed, incomplete, or SHA-mismatched data always becomes HOLD/BLOCKED.
"""
from __future__ import annotations

import re
from typing import Any

from core.control_tower_decision import ControlTowerDecisionRecord

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def rea_result_to_control_tower_decision(
    result: object, *, expected_sha: str
) -> ControlTowerDecisionRecord:
    """Convert adapter output into a Control Tower record, failing closed."""
    evidence_sha = expected_sha if isinstance(expected_sha, str) and _SHA_RE.fullmatch(expected_sha) else None
    blocked = ControlTowerDecisionRecord(
        reason_code="invalid_state",
        confidence=1.0,
        priority=100,
        next_action="HOLD",
        gate_status="BLOCKED",
        evidence_sha=evidence_sha,
    )
    if evidence_sha is None or not isinstance(result, dict):
        return blocked
    if result.get("schema_version") != 1 or type(result.get("schema_version")) is not int:
        return blocked
    if result.get("complete") is not True or result.get("target_sha") != expected_sha:
        return blocked
    if result.get("next_action") != "OBSERVE_ONLY":
        return blocked
    capabilities = result.get("capabilities")
    if not isinstance(capabilities, dict) or any(
        capabilities.get(key) is not expected
        for key, expected in (
            ("read_only", True),
            ("auto_approval", False),
            ("queue_mutation", False),
            ("patch_merge_deploy", False),
        )
    ):
        return blocked
    status = result.get("status")
    candidates = result.get("candidates")
    count = result.get("candidate_count")
    gate_status = result.get("gate_status")
    if not isinstance(candidates, list) or type(count) is not int or count != len(candidates):
        return blocked
    if status == "PASS" and count == 0 and gate_status == "PASS":
        return ControlTowerDecisionRecord(
            reason_code="evidence_sufficient",
            confidence=1.0,
            priority=0,
            next_action="OBSERVE_ONLY",
            gate_status="PASS",
            evidence_sha=expected_sha,
        )
    if status == "FINDINGS" and count > 0 and gate_status == "NOT_RUN":
        if any(
            not isinstance(candidate, dict)
            or candidate.get("status") != "REVIEW_REQUIRED"
            or candidate.get("next_action") != "OBSERVE_ONLY"
            or candidate.get("task_template_id") is not None
            or candidate.get("auto_approved") is not False
            for candidate in candidates
        ):
            return blocked
        return ControlTowerDecisionRecord(
            reason_code="rea_findings_review_required",
            confidence=1.0,
            priority=80,
            next_action="OBSERVE_ONLY",
            gate_status="NOT_RUN",
            evidence_sha=expected_sha,
        )
    return blocked


__all__ = ["rea_result_to_control_tower_decision"]
