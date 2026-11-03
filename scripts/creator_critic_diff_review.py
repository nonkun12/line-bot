"""Deterministic, fail-closed evidence gate for Creator/Critic diff reviews.

This reviewer validates provenance, task path boundaries, test execution evidence,
and the read-only REA report. It does not execute code, trust model verdicts,
modify task state, or authorize merge/deploy. Semantic review remains separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ALLOWED_STATUSES = {"added", "modified"}
_TOP_FIELDS = {
    "schema_version", "task_id", "base_sha", "head_sha", "allowed_paths",
    "changed_files", "diff_sha256", "tests", "rea",
}
_TEST_FIELDS = {"exit_code", "passed", "failed", "skipped", "report_sha256"}
_REA_FIELDS = {"status", "complete", "target_sha", "findings_count"}


class EvidenceInvalid(ValueError):
    """Evidence is malformed, incomplete, or outside the declared task scope."""


def _is_int(value: object) -> bool:
    return type(value) is int


def _safe_repo_path(value: object) -> bool:
    if not isinstance(value, str) or not value or chr(92) in value or value.startswith("/"):
        return False
    path = PurePosixPath(value)
    return not any(part in {"", ".", ".."} for part in value.split("/")) and not path.is_absolute()


def review_evidence(payload: object) -> dict[str, Any]:
    """Return PASS only when every provenance and deterministic safety gate passes."""
    if not isinstance(payload, dict) or set(payload) != _TOP_FIELDS:
        raise EvidenceInvalid("evidence_schema_invalid")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise EvidenceInvalid("evidence_schema_unsupported")
    if not isinstance(payload["task_id"], str) or not _TASK.fullmatch(payload["task_id"]):
        raise EvidenceInvalid("task_id_invalid")
    base_sha, head_sha = payload["base_sha"], payload["head_sha"]
    if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
        raise EvidenceInvalid("base_sha_invalid")
    if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha) or head_sha == base_sha:
        raise EvidenceInvalid("head_sha_invalid")

    allowed = payload["allowed_paths"]
    if (not isinstance(allowed, list) or not allowed
            or any(not _safe_repo_path(path) for path in allowed)
            or len(set(allowed)) != len(allowed)):
        raise EvidenceInvalid("allowed_paths_invalid")

    changed = payload["changed_files"]
    if not isinstance(changed, list) or not changed:
        raise EvidenceInvalid("changed_files_missing")
    seen: set[str] = set()
    violations: list[str] = []
    for item in changed:
        if not isinstance(item, dict) or set(item) != {"path", "status"}:
            raise EvidenceInvalid("changed_file_schema_invalid")
        path, status = item["path"], item["status"]
        if not _safe_repo_path(path) or path in seen:
            raise EvidenceInvalid("changed_file_path_invalid_or_duplicate")
        seen.add(path)
        if status not in _ALLOWED_STATUSES:
            violations.append("changed_file_operation_not_allowed")
        if path not in allowed:
            violations.append("changed_file_outside_task_allowlist")

    if not isinstance(payload["diff_sha256"], str) or not _DIGEST.fullmatch(payload["diff_sha256"]):
        raise EvidenceInvalid("diff_digest_invalid")

    tests = payload["tests"]
    if not isinstance(tests, dict) or set(tests) != _TEST_FIELDS:
        raise EvidenceInvalid("test_evidence_schema_invalid")
    for key in ("exit_code", "passed", "failed", "skipped"):
        if not _is_int(tests[key]) or tests[key] < 0:
            raise EvidenceInvalid("test_evidence_count_invalid")
    if not isinstance(tests["report_sha256"], str) or not _DIGEST.fullmatch(tests["report_sha256"]):
        raise EvidenceInvalid("test_report_digest_invalid")

    rea = payload["rea"]
    if not isinstance(rea, dict) or set(rea) != _REA_FIELDS:
        raise EvidenceInvalid("rea_evidence_schema_invalid")
    if rea["status"] not in {"PASS", "FINDINGS", "BLOCKED"}:
        raise EvidenceInvalid("rea_status_invalid")
    if type(rea["complete"]) is not bool:
        raise EvidenceInvalid("rea_completeness_invalid")
    if not isinstance(rea["target_sha"], str) or not _SHA.fullmatch(rea["target_sha"]):
        raise EvidenceInvalid("rea_target_sha_invalid")
    if not _is_int(rea["findings_count"]) or rea["findings_count"] < 0:
        raise EvidenceInvalid("rea_findings_count_invalid")

    reasons = list(dict.fromkeys(violations))
    if tests["exit_code"] != 0 or tests["failed"] != 0 or tests["passed"] < 1:
        reasons.append("tests_not_proven_passing")
    if rea["status"] != "PASS" or rea["complete"] is not True or rea["findings_count"] != 0:
        reasons.append("rea_not_clean_and_complete")
    if rea["target_sha"] != head_sha:
        reasons.append("rea_target_sha_mismatch")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    evidence_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "reviewer": "deterministic-evidence-gate",
        "verdict": "PASS" if not reasons else "HOLD",
        "reason_codes": reasons,
        "task_id": payload["task_id"],
        "base_sha": base_sha,
        "head_sha": head_sha,
        "evidence_sha256": evidence_sha256,
        "changed_file_count": len(changed),
        "test_counts": {
            "passed": tests["passed"], "failed": tests["failed"], "skipped": tests["skipped"],
        },
        "rea": {
            "status": rea["status"], "complete": rea["complete"],
            "target_sha": rea["target_sha"], "findings_count": rea["findings_count"],
        },
        "capabilities": {
            "semantic_code_review": False,
            "executes_code": False,
            "changes_task_or_approval_state": False,
            "authorizes_merge_or_deploy": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, help="JSON evidence envelope")
    parser.add_argument("--output", required=True, help="Output review JSON")
    args = parser.parse_args(argv)
    try:
        with open(args.evidence, encoding="utf-8") as stream:
            report = review_evidence(json.load(stream))
    except (OSError, json.JSONDecodeError, EvidenceInvalid):
        report = {
            "schema_version": 1,
            "reviewer": "deterministic-evidence-gate",
            "verdict": "HOLD",
            "reason_codes": ["evidence_unavailable_or_invalid"],
            "capabilities": {
                "semantic_code_review": False, "executes_code": False,
                "changes_task_or_approval_state": False, "authorizes_merge_or_deploy": False,
            },
        }
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\\n")
    print("CREATOR_CRITIC_DIFF_REVIEW=" + report["verdict"])
    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
