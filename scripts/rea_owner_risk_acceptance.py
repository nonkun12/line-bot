"""Record owner risk acceptance without impersonating independent review.

This receipt is audit evidence only. It never lowers scanner risk and never
authorizes execution, patching, HOLD removal, merging, or deployment.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIFF = re.compile(r"^[0-9a-f]{64}$")
_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def build_owner_risk_acceptance(
    report: dict[str, Any], *, actor: str, repository_owner: str,
    decision: str, run_id: int, accepted_at: str,
) -> dict[str, Any]:
    """Build a SHA-bound, owner-only receipt; never authorize a merge."""
    if not isinstance(report, dict) or report.get("complete") is not True:
        raise ValueError("scan_incomplete")
    base_sha = report.get("base_sha")
    target_sha = report.get("target_sha")
    diff_sha256 = report.get("diff_sha256")
    if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
        raise ValueError("base_sha_invalid")
    if not isinstance(target_sha, str) or not _SHA.fullmatch(target_sha):
        raise ValueError("target_sha_invalid")
    if not isinstance(diff_sha256, str) or not _DIFF.fullmatch(diff_sha256):
        raise ValueError("diff_sha256_invalid")
    if not isinstance(actor, str) or not actor or not isinstance(repository_owner, str) or not repository_owner:
        raise ValueError("actor_identity_missing")
    if actor.casefold() != repository_owner.casefold():
        raise ValueError("actor_not_repository_owner")
    if decision not in {"ACCEPT", "DECLINE"}:
        raise ValueError("decision_invalid")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise ValueError("run_id_invalid")
    try:
        parsed = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("accepted_at_invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("accepted_at_timezone_missing")

    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings_invalid")
    severities = [item.get("severity") for item in findings if isinstance(item, dict)]
    if len(severities) != len(findings) or any(value not in _RANK for value in severities):
        raise ValueError("finding_severity_invalid")
    risk = max(severities, key=lambda value: _RANK[value], default="LOW")
    eligible = risk == "LOW" and not findings
    status = "ACCEPTED" if decision == "ACCEPT" and eligible else (
        "DECLINED" if decision == "DECLINE" else "BLOCKED"
    )
    return {
        "schema_version": 1,
        "status": status,
        "decision": decision,
        "actor": actor,
        "actor_role": "REPOSITORY_OWNER",
        "repository_owner": repository_owner,
        "base_sha": base_sha,
        "target_sha": target_sha,
        "diff_sha256": diff_sha256,
        "risk": risk,
        "finding_count": len(findings),
        "accepted_at": accepted_at,
        "workflow_run_id": run_id,
        "human_review_status": "NOT_PROVIDED",
        "independent_review_substituted": False,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_authorized": False,
        "deploy_authorized": False,
    }
