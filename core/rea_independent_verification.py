"""Validate the independent GitHub Actions REA receipt against trusted run metadata.

The caller must obtain run_metadata directly from the GitHub Actions API. A receipt
alone is untrusted and can never establish a successful independent test run.
This adapter reports test evidence only; risk and all authorization remain closed.
"""
from __future__ import annotations

import re
from typing import Any

WORKFLOW_PATH = ".github/workflows/rea-independent-verification.yml"
REPOSITORY = "nonkun12/line-bot"


def _unknown(reason: str) -> dict[str, Any]:
    return {"tests": "UNKNOWN", "reason_code": reason}


def evaluate_independent_verification_receipt(
    receipt: object,
    run_metadata: object,
    *,
    expected_sha: str,
    repository: str = REPOSITORY,
    workflow_path: str = WORKFLOW_PATH,
) -> dict[str, Any]:
    """Return test status only when receipt and trusted API run identity agree.

    run_metadata must be the GitHub Actions workflow-run object fetched from the
    trusted GitHub API, not a field copied from the downloadable artifact.
    """
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        return _unknown("expected_sha_invalid")
    if not isinstance(run_metadata, dict):
        return _unknown("trusted_run_metadata_missing")

    if run_metadata.get("status") != "completed":
        return {"tests": "NOT_RUN", "reason_code": "verification_run_incomplete"}
    if run_metadata.get("conclusion") != "success":
        return {"tests": "FAIL", "reason_code": "verification_run_failed"}

    repo = run_metadata.get("repository")
    if not isinstance(repo, dict) or repo.get("full_name") != repository:
        return _unknown("verification_repository_mismatch")
    if run_metadata.get("path") != workflow_path:
        return _unknown("verification_workflow_path_mismatch")
    if run_metadata.get("head_sha") != expected_sha:
        return _unknown("verification_run_sha_mismatch")

    event = run_metadata.get("event")
    if event == "pull_request":
        pull_requests = run_metadata.get("pull_requests")
        if not isinstance(pull_requests, list) or not pull_requests:
            return _unknown("verification_pull_request_binding_missing")
        pr = pull_requests[0]
        if not isinstance(pr, dict):
            return _unknown("verification_pull_request_binding_invalid")
        head, base = pr.get("head"), pr.get("base")
        if not isinstance(head, dict) or head.get("sha") != expected_sha:
            return _unknown("verification_pull_request_head_mismatch")
        if not isinstance(base, dict) or base.get("ref") != "main":
            return _unknown("verification_pull_request_base_mismatch")
        if base.get("sha") != receipt.get("base_sha"):
            return _unknown("verification_receipt_base_sha_mismatch")
    elif event == "push":
        branch = run_metadata.get("head_branch")
        if not isinstance(branch, str) or not branch.startswith("line-dev/"):
            return _unknown("verification_push_branch_not_allowed")
    else:
        return _unknown("verification_event_not_allowed")

    if not isinstance(receipt, dict):
        return _unknown("verification_receipt_missing")
    if receipt.get("schema_version") != 1:
        return _unknown("verification_receipt_schema_mismatch")
    if receipt.get("run_id") != run_metadata.get("id"):
        return _unknown("verification_receipt_run_id_mismatch")
    if receipt.get("verified_sha") != expected_sha:
        return _unknown("verification_receipt_sha_mismatch")
    base_sha = receipt.get("base_sha")
    if not isinstance(base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        return _unknown("verification_receipt_base_sha_invalid")
    if receipt.get("identity_outcome") != "SUCCESS":
        return _unknown("verification_identity_not_passed")
    if receipt.get("test_outcome") == "FAILURE":
        return {"tests": "FAIL", "reason_code": "independent_pytest_failed"}
    if receipt.get("test_outcome") != "SUCCESS":
        return {"tests": "NOT_RUN", "reason_code": "independent_pytest_not_passed"}

    authority_fields = (
        "execution_authorized", "patch_authorized",
        "hold_clear_authorized", "merge_deploy_authorized",
    )
    if any(receipt.get(field) is not False for field in authority_fields):
        return _unknown("verification_receipt_authority_violation")

    return {
        "tests": "PASS",
        "reason_code": "independent_pytest_passed",
        "verified_sha": expected_sha,
        "verification_run_id": run_metadata.get("id"),
        "risk": "UNKNOWN",
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }


__all__ = ["evaluate_independent_verification_receipt"]
