from __future__ import annotations

from core.rea_independent_verification import (
    WORKFLOW_ID,
    WORKFLOW_PATH,
    evaluate_independent_verification_receipt,
)

SHA = "a" * 40
BASE = "b" * 40


def receipt(**overrides):
    value = {
        "schema_version": 1,
        "verified_sha": SHA,
        "base_sha": BASE,
        "test_outcome": "SUCCESS",
        "identity_outcome": "SUCCESS",
        "risk": "UNKNOWN",
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    value.update(overrides)
    return value


def run(**overrides):
    value = {
        "id": 123,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "nonkun12/line-bot"},
        "workflow_id": WORKFLOW_ID,
        "path": WORKFLOW_PATH,
        "event": "pull_request",
        "head_sha": SHA,
        "pull_requests": [{
            "head": {"sha": SHA},
            "base": {"ref": "main"},
        }],
    }
    value.update(overrides)
    return value


def test_trusted_sha_bound_receipt_reports_tests_pass_only():
    result = evaluate_independent_verification_receipt(receipt(), run(), expected_sha=SHA)
    assert result["tests"] == "PASS"
    assert result["verified_sha"] == SHA
    assert result["risk"] == "UNKNOWN"
    assert result["execution_authorized"] is False
    assert result["patch_authorized"] is False
    assert result["hold_clear_authorized"] is False
    assert result["merge_deploy_authorized"] is False


def test_receipt_alone_is_never_trusted():
    result = evaluate_independent_verification_receipt(receipt(), None, expected_sha=SHA)
    assert result["tests"] == "UNKNOWN"
    assert result["reason_code"] == "trusted_run_metadata_missing"


def test_run_sha_and_receipt_sha_must_match_expected_sha():
    assert evaluate_independent_verification_receipt(
        receipt(), run(head_sha="c" * 40), expected_sha=SHA
    )["tests"] == "UNKNOWN"
    assert evaluate_independent_verification_receipt(
        receipt(verified_sha="c" * 40), run(), expected_sha=SHA
    )["tests"] == "UNKNOWN"


def test_wrong_workflow_repository_or_event_is_rejected():
    assert evaluate_independent_verification_receipt(
        receipt(), run(workflow_id=WORKFLOW_ID + 1), expected_sha=SHA
    )["tests"] == "UNKNOWN"
    assert evaluate_independent_verification_receipt(
        receipt(), run(repository={"full_name": "attacker/repo"}), expected_sha=SHA
    )["tests"] == "UNKNOWN"
    assert evaluate_independent_verification_receipt(
        receipt(), run(event="push"), expected_sha=SHA
    )["tests"] == "UNKNOWN"


def test_failed_or_incomplete_runs_do_not_pass():
    assert evaluate_independent_verification_receipt(
        receipt(), run(conclusion="failure"), expected_sha=SHA
    )["tests"] == "FAIL"
    assert evaluate_independent_verification_receipt(
        receipt(), run(status="in_progress", conclusion=None), expected_sha=SHA
    )["tests"] == "NOT_RUN"


def test_receipt_cannot_grant_authority_or_hide_failed_tests():
    assert evaluate_independent_verification_receipt(
        receipt(execution_authorized=True), run(), expected_sha=SHA
    )["tests"] == "UNKNOWN"
    assert evaluate_independent_verification_receipt(
        receipt(test_outcome="FAILURE"), run(), expected_sha=SHA
    )["tests"] == "FAIL"


def test_wrong_pull_request_base_is_rejected():
    pr = {"head": {"sha": SHA}, "base": {"ref": "other"}}
    assert evaluate_independent_verification_receipt(
        receipt(), run(pull_requests=[pr]), expected_sha=SHA
    )["tests"] == "UNKNOWN"
