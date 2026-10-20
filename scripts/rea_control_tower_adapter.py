"""Bind read-only REA evidence to the Control Tower's pre-execution HEAD.

This adapter is diagnostic only. It cannot authorize task IDs, clear HOLD,
write queues/state, patch files, or merge/deploy.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.rea_readonly_scanner import ALLOWED_ROOTS, ALLOWED_SUFFIXES, scan_repository

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FINDING_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BLOCKING_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
_SAFE_SEVERITIES = frozenset({"LOW", "MEDIUM"})
_PASS_FIELDS = frozenset({
    "gate", "mode", "target_sha", "scanner_status", "finding_count",
    "critical_count", "blocking_count", "findings_truncated", "findings",
    "execution_authorized", "patch_authorized", "hold_clear_authorized",
    "merge_deploy_authorized",
})
_FINDING_FIELDS = frozenset({
    "finding_id", "category", "severity", "path", "line", "status",
})


def prepare_rea_evidence(
    repo_root: str | Path,
    *,
    expected_sha: str,
) -> dict[str, Any]:
    """Return sanitized SHA-bound evidence; block on uncertainty or high severity."""
    if not isinstance(expected_sha, str) or not _SHA_RE.fullmatch(expected_sha):
        return _blocked("expected_sha_invalid")

    try:
        report = scan_repository(repo_root)
    except Exception:
        # Do not leak filesystem paths, exception text, or environment details.
        return _blocked("rea_scan_incomplete")

    if not isinstance(report, dict):
        return _blocked("rea_report_invalid")
    if report.get("target_sha") != expected_sha:
        return _blocked("rea_sha_mismatch")
    if report.get("complete") is not True or report.get("status") == "BLOCKED":
        return _blocked("rea_scan_incomplete")

    findings = report.get("findings")
    if not isinstance(findings, list):
        return _blocked("rea_findings_invalid")
    safe_findings: list[dict[str, Any]] = []
    seen_finding_ids: set[str] = set()
    critical_count = 0
    blocking_count = 0
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
            not isinstance(path, str) or not _safe_path(path)
            or not isinstance(category, str) or not _CATEGORY_RE.fullmatch(category)
            or not isinstance(severity, str)
            or severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
            or (line is not None and (type(line) is not int or line < 1 or line > 10_000_000))
            or not isinstance(finding_id, str) or not _FINDING_ID_RE.fullmatch(finding_id)
            or finding_id in seen_finding_ids
        ):
            return _blocked("rea_finding_schema_invalid")
        seen_finding_ids.add(finding_id)
        if severity == "CRITICAL":
            critical_count += 1
        if severity in _BLOCKING_SEVERITIES:
            blocking_count += 1
        safe_findings.append({
            "finding_id": finding_id,
            "category": category,
            "severity": severity,
            "path": path,
            "line": line,
            "status": "REVIEW_REQUIRED",
        })

    scanner_status = report.get("status")
    if not isinstance(scanner_status, str) or scanner_status not in {"PASS", "FINDINGS"}:
        return _blocked("rea_scanner_status_invalid")
    if scanner_status != ("FINDINGS" if safe_findings else "PASS"):
        return _blocked("rea_scanner_status_inconsistent")

    common = {
        "target_sha": expected_sha,
        "scanner_status": scanner_status,
        "finding_count": len(safe_findings),
        "critical_count": critical_count,
        "blocking_count": blocking_count,
        "findings_truncated": len(safe_findings) > 100,
        "findings": safe_findings[:100],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    if blocking_count:
        return {"gate": "BLOCKED", "reason_code": "rea_high_or_critical_finding", **common}
    return {"gate": "PASS", "mode": "OBSERVE_ONLY", **common}


def _safe_path(path: str) -> bool:
    """Accept only normalized repository-relative paths in scanner allowlisted roots."""
    if (
        not path
        or len(path) > 512
        or "\\" in path
        or path.startswith("/")
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
        or "\x00" in path
    ):
        return False
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    normalized = parsed.as_posix()
    return (
        normalized == path
        and any(path.startswith(root) for root in ALLOWED_ROOTS)
        and Path(path).suffix.lower() in ALLOWED_SUFFIXES
    )


def rea_evidence_is_valid_pass(evidence: object, *, expected_sha: str) -> bool:
    """Strictly validate a PASS record at the execution boundary; grant no authority."""
    if not isinstance(expected_sha, str) or not _SHA_RE.fullmatch(expected_sha):
        return False
    if not isinstance(evidence, dict) or set(evidence) != _PASS_FIELDS:
        return False

    findings = evidence.get("findings")
    finding_count = evidence.get("finding_count")
    truncated = evidence.get("findings_truncated")
    scanner_status = evidence.get("scanner_status")
    if (
        evidence.get("gate") != "PASS"
        or evidence.get("mode") != "OBSERVE_ONLY"
        or evidence.get("target_sha") != expected_sha
        or not isinstance(scanner_status, str)
        or scanner_status not in {"PASS", "FINDINGS"}
        or type(finding_count) is not int
        or finding_count < 0
        or not isinstance(findings, list)
        or len(findings) > 100
        or type(truncated) is not bool
        or (truncated and (finding_count <= 100 or len(findings) != 100))
        or (not truncated and finding_count != len(findings))
        or scanner_status != ("FINDINGS" if finding_count else "PASS")
        or type(evidence.get("critical_count")) is not int
        or evidence.get("critical_count") != 0
        or type(evidence.get("blocking_count")) is not int
        or evidence.get("blocking_count") != 0
        or evidence.get("execution_authorized") is not False
        or evidence.get("patch_authorized") is not False
        or evidence.get("hold_clear_authorized") is not False
        or evidence.get("merge_deploy_authorized") is not False
    ):
        return False

    seen_finding_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != _FINDING_FIELDS:
            return False
        if (
            not isinstance(finding.get("finding_id"), str)
            or not _FINDING_ID_RE.fullmatch(finding["finding_id"])
            or finding["finding_id"] in seen_finding_ids
            or not isinstance(finding.get("category"), str)
            or not _CATEGORY_RE.fullmatch(finding["category"])
            or not isinstance(finding.get("severity"), str)
            or finding.get("severity") not in _SAFE_SEVERITIES
            or not isinstance(finding.get("path"), str)
            or not _safe_path(finding["path"])
            or (finding.get("line") is not None
                and (type(finding["line"]) is not int or finding["line"] < 1 or finding["line"] > 10_000_000))
            or finding.get("status") != "REVIEW_REQUIRED"
        ):
            return False
        seen_finding_ids.add(finding["finding_id"])
    return True


def publish_row_has_valid_gates(row: object, *, expected_sha: str) -> bool:
    """Independently validate the exact successful run before branch publication."""
    if not isinstance(row, dict):
        return False
    task_id = row.get("task_id")
    base_sha = row.get("base_sha")
    produced_sha = row.get("produced_sha")
    status = row.get("status")
    exit_code = row.get("exit_code")
    if (
        not isinstance(task_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id)
        or status not in {"PASS", "NO_CHANGE"}
        or type(exit_code) is not int
        or exit_code != 0
        or not isinstance(base_sha, str)
        or not _SHA_RE.fullmatch(base_sha)
        or base_sha != expected_sha
        or not isinstance(produced_sha, str)
        or not _SHA_RE.fullmatch(produced_sha)
        or (status == "NO_CHANGE" and produced_sha != base_sha)
    ):
        return False
    if not rea_evidence_is_valid_pass(row.get("rea"), expected_sha=base_sha):
        return False
    run_nonce = row.get("run_nonce")
    recovery = row.get("recovery_ai")
    expected_recovery_evidence = {
        "task_id": task_id,
        "base_sha": base_sha,
        "produced_sha": produced_sha,
        "run_nonce": run_nonce,
    }
    if (
        not isinstance(run_nonce, str)
        or not re.fullmatch(r"[0-9a-f]{32}", run_nonce)
        or not isinstance(recovery, dict)
        or recovery.get("recorded") is not True
        or recovery.get("verified") is not True
        or recovery.get("status") != status
        or recovery.get("evidence") != expected_recovery_evidence
    ):
        return False
    control_tower = row.get("control_tower")
    if not isinstance(control_tower, dict) or control_tower.get("recorded") is not True:
        return False
    orchestration = control_tower.get("orchestration")
    return (
        isinstance(orchestration, dict)
        and orchestration.get("phase") == "REPORT"
        and orchestration.get("next_action") == "REPORT_VERIFIED_SUCCESS"
        and orchestration.get("reason_code") == "verified_success"
        and orchestration.get("allow_continue") is True
        and orchestration.get("task_id") == task_id
        and orchestration.get("repair_executed") is False
    )

def _blocked(reason_code: str) -> dict[str, Any]:
    return {
        "gate": "BLOCKED",
        "reason_code": reason_code,
        "target_sha": None,
        "scanner_status": "BLOCKED",
        "finding_count": 0,
        "critical_count": 0,
        "blocking_count": 0,
        "findings_truncated": False,
        "findings": [],
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }


__all__ = [
    "prepare_rea_evidence",
    "rea_evidence_is_valid_pass",
    "publish_row_has_valid_gates",
]
