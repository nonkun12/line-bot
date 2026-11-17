"""Strict validation for independently collected test evidence.

This validates evidence structure and identity only. It does not authenticate an
artifact's origin. Callers MUST establish that the artifact came from the trusted
verification workflow and supply expected identity/diff values from trusted event
metadata and a fresh repository scan. Never accept identity or sandbox claims
solely from the test process.
"""
from __future__ import annotations

import re
from typing import Any

_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA64 = re.compile(r"[0-9a-f]{64}")
_REQUIRED = {
    "schema_version", "run_id", "run_attempt", "task_id", "base_sha",
    "head_sha", "diff_sha256", "outcome", "exit_code", "tests_collected",
    "tests_passed", "tests_failed", "tests_skipped", "test_command_sha256",
}


def _result(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason,
        "tests": "PASS" if status == "PASS" else ("FAIL" if status == "FAIL" else "NOT_RUN"),
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }


def validate_independent_test_evidence(
    evidence: object,
    *,
    expected: object,
    trusted_collector: bool,
) -> dict[str, Any]:
    """Validate a trusted collector's result against independently known identity.

    trusted_collector must be derived by the caller from workflow provenance,
    never from a field inside evidence. expected must come from trusted event
    metadata and a fresh diff scan, not from the test artifact.
    """
    if not trusted_collector:
        return _result("HOLD", "trusted_collector_not_established")
    if not isinstance(evidence, dict) or not isinstance(expected, dict):
        return _result("HOLD", "evidence_or_expected_identity_invalid")
    if not _REQUIRED.issubset(evidence):
        return _result("HOLD", "independent_test_evidence_missing_fields")
    if evidence.get("schema_version") != 1:
        return _result("HOLD", "independent_test_schema_unsupported")

    identity_fields = ("run_id", "run_attempt", "task_id", "base_sha", "head_sha", "diff_sha256")
    for field in identity_fields:
        if field not in expected or evidence.get(field) != expected.get(field):
            return _result("HOLD", "independent_test_identity_mismatch")

    if not isinstance(evidence.get("run_id"), (str, int)) or not str(evidence["run_id"]).isdigit():
        return _result("HOLD", "independent_test_run_id_invalid")
    if not isinstance(evidence.get("run_attempt"), int) or isinstance(evidence["run_attempt"], bool) or evidence["run_attempt"] < 1:
        return _result("HOLD", "independent_test_attempt_invalid")
    if not isinstance(evidence.get("task_id"), str) or not evidence["task_id"].strip():
        return _result("HOLD", "independent_test_task_id_invalid")
    if not isinstance(evidence.get("base_sha"), str) or not _SHA40.fullmatch(evidence["base_sha"]):
        return _result("HOLD", "independent_test_base_sha_invalid")
    if not isinstance(evidence.get("head_sha"), str) or not _SHA40.fullmatch(evidence["head_sha"]):
        return _result("HOLD", "independent_test_head_sha_invalid")
    if not isinstance(evidence.get("diff_sha256"), str) or not _SHA64.fullmatch(evidence["diff_sha256"]):
        return _result("HOLD", "independent_test_diff_hash_invalid")
    if not isinstance(evidence.get("test_command_sha256"), str) or not _SHA64.fullmatch(evidence["test_command_sha256"]):
        return _result("HOLD", "independent_test_command_hash_invalid")

    counts = ("tests_collected", "tests_passed", "tests_failed", "tests_skipped", "exit_code")
    if any(not isinstance(evidence.get(k), int) or isinstance(evidence[k], bool) or evidence[k] < 0 for k in counts):
        return _result("HOLD", "independent_test_counts_invalid")

    outcome = evidence.get("outcome")
    if outcome in {"timeout", "cancelled", "skipped"}:
        return _result("BLOCKED", "independent_test_runner_" + outcome)
    if outcome == "failure" or evidence["exit_code"] != 0 or evidence["tests_failed"] > 0:
        return _result("FAIL", "independent_tests_failed")
    if outcome != "success":
        return _result("HOLD", "independent_test_outcome_unknown")
    if evidence["tests_collected"] < 1 or evidence["tests_passed"] < 1:
        return _result("HOLD", "independent_tests_zero_executed")
    if evidence["tests_passed"] + evidence["tests_failed"] + evidence["tests_skipped"] > evidence["tests_collected"]:
        return _result("HOLD", "independent_test_counts_inconsistent")
    if evidence["tests_skipped"] > 0:
        return _result("HOLD", "independent_tests_skipped")
    return _result("PASS", "independent_test_evidence_verified")


__all__ = ["validate_independent_test_evidence"]
