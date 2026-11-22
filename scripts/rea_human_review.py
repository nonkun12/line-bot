"""Validate authenticated, SHA-bound REA human-review evidence.

This module never contacts GitHub. The workflow supplies comment metadata fetched
from GitHub's authenticated API; this module verifies that metadata is bound to
the exact scanned commit and only acknowledges the narrowly designated finding.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIFF_RE = re.compile(r"^[0-9a-f]{64}$")
_MARKER = "REA-HUMAN-REVIEW: APPROVED"
_REVIEWABLE = {
    ("manual_review_required", "distributed_loop_trigger.py",
     "sensitive_entrypoint_requires_human_review"),
}


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("review_timestamp_missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("review_timestamp_timezone_missing")
    return parsed


def _body_head_sha(body: str) -> str:
    if not isinstance(body, str):
        raise ValueError("review_comment_body_missing")
    lines = [line.strip() for line in body.splitlines()]
    if lines.count(_MARKER) != 1:
        raise ValueError("review_marker_invalid")
    values = [line.split(":", 1)[1].strip() for line in lines
              if line.startswith("HEAD_SHA:")]
    if len(values) != 1 or not _SHA_RE.fullmatch(values[0]):
        raise ValueError("review_head_sha_invalid")
    return values[0]


def apply_human_review_attestation(
    report: dict[str, Any], attestation: dict[str, Any]
) -> dict[str, Any]:
    """Mark only the designated finding reviewed after strict identity checks.

    The caller must obtain comment fields from GitHub's authenticated API. A
    local JSON file or workflow input is not an accepted source of identity.
    """
    if not isinstance(report, dict) or not isinstance(attestation, dict):
        raise ValueError("review_evidence_invalid")
    target_sha = report.get("target_sha")
    diff_sha256 = report.get("diff_sha256")
    if not isinstance(target_sha, str) or not _SHA_RE.fullmatch(target_sha):
        raise ValueError("report_target_sha_invalid")
    if not isinstance(diff_sha256, str) or not _DIFF_RE.fullmatch(diff_sha256):
        raise ValueError("report_diff_hash_invalid")
    if attestation.get("expected_head_sha") != target_sha:
        raise ValueError("review_head_sha_mismatch")
    if attestation.get("expected_diff_sha256") != diff_sha256:
        raise ValueError("review_diff_hash_mismatch")

    reviewer = attestation.get("reviewer_login")
    pr_author = attestation.get("pr_author_login")
    if not isinstance(reviewer, str) or not reviewer or reviewer != pr_author:
        raise ValueError("reviewer_not_authenticated_pr_author")

    comment_id = attestation.get("comment_id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id <= 0:
        raise ValueError("review_comment_id_invalid")
    repo = attestation.get("repo_full_name")
    pr_number = attestation.get("pr_number")
    comment_url = attestation.get("comment_url")
    if (not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0
            or not isinstance(comment_url, str)
            or not comment_url.startswith(f"https://github.com/{repo}/pull/{pr_number}#issuecomment-")):
        raise ValueError("review_comment_origin_invalid")

    if _body_head_sha(attestation.get("comment_body")) != target_sha:
        raise ValueError("review_comment_head_mismatch")
    created_at = _timestamp(attestation.get("comment_created_at"))
    head_commit_at = _timestamp(attestation.get("head_commit_at"))
    if created_at < head_commit_at:
        raise ValueError("review_comment_predates_head")

    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("report_findings_invalid")
    matching = [
        item for item in findings
        if isinstance(item, dict)
        and (item.get("category"), item.get("evidence", {}).get("path"),
             item.get("evidence", {}).get("check")) in _REVIEWABLE
        and item.get("target_sha") == target_sha
        and item.get("status") == "REVIEW_REQUIRED"
    ]
    if len(matching) != 1:
        raise ValueError("reviewable_finding_not_unique")

    updated = dict(report)
    updated_findings = [dict(item) if isinstance(item, dict) else item for item in findings]
    for item in updated_findings:
        if item is matching[0]:
            item["status"] = "HUMAN_REVIEWED"
            item["human_review"] = {
                "reviewer_login": reviewer,
                "comment_id": comment_id,
                "comment_url": comment_url,
                "comment_created_at": attestation["comment_created_at"],
                "target_sha": target_sha,
                "diff_sha256": diff_sha256,
            }
    updated["findings"] = updated_findings
    updated["human_review_attestation"] = {
        "status": "VERIFIED",
        "reviewer_login": reviewer,
        "comment_id": comment_id,
        "comment_url": comment_url,
        "comment_created_at": attestation["comment_created_at"],
        "target_sha": target_sha,
        "diff_sha256": diff_sha256,
        "reviewed_paths": ["distributed_loop_trigger.py"],
    }
    return updated
