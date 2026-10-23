"""Convert a validated REA report into non-executable Control Tower review candidates.

This adapter is intentionally advisory-only: it never creates issues, changes a
queue/catalog/HOLD state, or grants task execution, patch, merge, or deploy rights.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_ROOTS = (".github/workflows/", "core/", "scripts/", "tests/", "docs/rea/")


def build_review_candidates(report: object, *, expected_sha: str) -> dict[str, Any]:
    """Return review-only candidates, failing closed on incomplete evidence."""
    blocked = {
        "schema_version": 1,
        "status": "BLOCKED",
        "complete": False,
        "next_action": "OBSERVE_ONLY",
        "gate_status": "BLOCKED",
        "target_sha": expected_sha if isinstance(expected_sha, str) else None,
        "candidate_count": 0,
        "candidates": [],
        "capabilities": {
            "read_only": True,
            "auto_approval": False,
            "queue_mutation": False,
            "patch_merge_deploy": False,
        },
    }
    if not isinstance(expected_sha, str) or not _SHA_RE.fullmatch(expected_sha):
        return blocked
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        return blocked
    if report.get("target_sha") != expected_sha:
        return blocked
    if report.get("complete") is not True:
        return blocked
    status = report.get("status")
    findings = report.get("findings")
    if status not in {"PASS", "FINDINGS"} or not isinstance(findings, list):
        return blocked
    if status == "PASS" and findings:
        return blocked
    if status == "FINDINGS" and not findings:
        return blocked
    if report.get("findings_count") != len(findings):
        return blocked

    candidates: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            return blocked
        if finding.get("target_sha") != expected_sha:
            return blocked
        finding_id = finding.get("finding_id")
        category = finding.get("category")
        severity = finding.get("severity")
        evidence = finding.get("evidence")
        if not isinstance(finding_id, str) or not re.fullmatch(r"[0-9a-f]{16}", finding_id):
            return blocked
        if not isinstance(category, str) or not category or len(category) > 80:
            return blocked
        if not isinstance(severity, str) or severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            return blocked
        if not isinstance(evidence, dict):
            return blocked
        path = evidence.get("path")
        line = evidence.get("line")
        check = evidence.get("check")
        if not isinstance(path, str) or not path.startswith(_ALLOWED_ROOTS):
            return blocked
        if any(part in {"", ".", ".."} for part in path.split("/")):
            return blocked
        if line is not None and (type(line) is not int or line < 1):
            return blocked
        if not isinstance(check, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", check):
            return blocked
        candidates.append({
            "finding_id": finding_id,
            "category": category,
            "severity": severity,
            "evidence": {"path": path, "line": line, "check": check},
            "status": "REVIEW_REQUIRED",
            "next_action": "OBSERVE_ONLY",
            "task_template_id": None,
            "auto_approved": False,
        })

    return {
        "schema_version": 1,
        "status": status,
        "complete": True,
        "next_action": "OBSERVE_ONLY",
        "gate_status": "NOT_RUN" if candidates else "PASS",
        "target_sha": expected_sha,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "capabilities": {
            "read_only": True,
            "auto_approval": False,
            "queue_mutation": False,
            "patch_merge_deploy": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="REA JSON report")
    parser.add_argument("--expected-sha", required=True, help="Exact 40-character source HEAD SHA")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        result = build_review_candidates(None, expected_sha=args.expected_sha)
        print(json.dumps(result, sort_keys=True))
        return 2
    result = build_review_candidates(report, expected_sha=args.expected_sha)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"PASS", "FINDINGS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
