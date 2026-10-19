"""Bind read-only REA evidence to the Control Tower's pre-execution HEAD.

This adapter is diagnostic only. It cannot authorize task IDs, clear HOLD,
write queues/state, patch files, or merge/deploy.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scripts.rea_readonly_scanner import scan_repository

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def prepare_rea_evidence(
    repo_root: str | Path,
    *,
    expected_sha: str,
) -> dict[str, Any]:
    """Return a sanitized, SHA-bound diagnostic record; fail closed on uncertainty."""
    if not isinstance(expected_sha, str) or not _SHA_RE.fullmatch(expected_sha):
        return _blocked("expected_sha_invalid")

    try:
        report = scan_repository(repo_root)
    except Exception:
        # Do not leak filesystem paths, exception text, or environment details.
        return _blocked("rea_scan_incomplete")

    if report.get("target_sha") != expected_sha:
        return _blocked("rea_sha_mismatch")
    if report.get("complete") is not True or report.get("status") == "BLOCKED":
        return _blocked("rea_scan_incomplete")

    findings = report.get("findings")
    if not isinstance(findings, list):
        return _blocked("rea_findings_invalid")
    safe_findings: list[dict[str, Any]] = []
    critical_count = 0
    for finding in findings:
        if not isinstance(finding, dict):
            return _blocked("rea_finding_invalid")
        evidence = finding.get("evidence")
        if not isinstance(evidence, dict):
            return _blocked("rea_finding_evidence_invalid")
        path = evidence.get("path")
        category = finding.get("category")
        severity = finding.get("severity")
        line = evidence.get("line")
        finding_id = finding.get("finding_id")
        if (
            not isinstance(path, str) or not path
            or not isinstance(category, str) or not category
            or severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
            or (line is not None and (type(line) is not int or line < 1))
            or not isinstance(finding_id, str) or not re.fullmatch(r"[0-9a-f]{16}", finding_id)
        ):
            return _blocked("rea_finding_schema_invalid")
        if severity == "CRITICAL":
            critical_count += 1
        safe_findings.append({
            "finding_id": finding_id,
            "category": category,
            "severity": severity,
            "path": path,
            "line": line,
            "status": "REVIEW_REQUIRED",
        })

    if critical_count:
        return {
            "gate": "BLOCKED",
            "reason_code": "rea_critical_finding",
            "target_sha": expected_sha,
            "scanner_status": report["status"],
            "finding_count": len(safe_findings),
            "critical_count": critical_count,
            "findings": safe_findings,
            "execution_authorized": False,
            "patch_authorized": False,
            "hold_clear_authorized": False,
            "merge_deploy_authorized": False,
        }

    return {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": expected_sha,
        "scanner_status": report["status"],
        "finding_count": len(safe_findings),
        "critical_count": 0,
        "findings_truncated": len(safe_findings) > 100,
        "findings": safe_findings[:100],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }


def _blocked(reason_code: str) -> dict[str, Any]:
    return {
        "gate": "BLOCKED",
        "reason_code": reason_code,
        "target_sha": None,
        "scanner_status": "BLOCKED",
        "finding_count": 0,
        "critical_count": 0,
        "findings": [],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }


__all__ = ["prepare_rea_evidence"]
