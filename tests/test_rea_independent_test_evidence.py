from __future__ import annotations

from core.rea_independent_test_evidence import validate_independent_test_evidence


BASE = "1" * 40
HEAD = "2" * 40
DIFF = "a" * 64
COMMAND = "b" * 64


def expected(**overrides):
    value = {
        "run_id": "12345",
        "run_attempt": 2,
        "task_id": "task-001",
        "base_sha": BASE,
        "head_sha": HEAD,
        "diff_sha256": DIFF,
        "test_command_sha256": COMMAND,
    }
    value.update(overrides)
    return value


def evidence(**overrides):
    value = {
        "schema_version": 1,
        **expected(),
        "outcome": "success",
        "exit_code": 0,
        "tests_collected": 12,
        "tests_passed": 12,
        "tests_failed": 0,
        "tests_skipped": 0,
        "test_command_sha256": COMMAND,
    }
    value.update(overrides)
    return value


def validate(item=None, identity=None, trusted=True):
    return validate_independent_test_evidence(
        evidence() if item is None else item,
        expected=expected() if identity is None else identity,
        trusted_collector=trusted,
    )


def test_valid_evidence_passes_without_authority():
    result = validate()
    assert result["status"] == "PASS"
    assert result["tests"] == "PASS"
    assert result["merge_deploy_authorized"] is False


def test_untrusted_collector_holds():
    result = validate(trusted=False)
    assert result["status"] == "HOLD"
    assert result["reason_code"] == "trusted_collector_not_established"


def test_missing_evidence_fields_hold():
    item = evidence()
    del item["test_command_sha256"]
    assert validate(item)["status"] == "HOLD"


def test_identity_mismatch_holds():
    for key, value in (
        ("run_id", "999"),
        ("run_attempt", 1),
        ("task_id", "other"),
        ("base_sha", "3" * 40),
        ("head_sha", "4" * 40),
        ("diff_sha256", "c" * 64),
    ):
        item = evidence()
        item[key] = value
        assert validate(item)["status"] == "HOLD"


def test_zero_tests_or_all_skipped_hold():
    assert validate(evidence(tests_collected=0, tests_passed=0))["status"] == "HOLD"
    assert validate(evidence(tests_passed=0, tests_skipped=12))["status"] == "HOLD"


def test_test_failure_is_fail():
    assert validate(evidence(outcome="failure", exit_code=1, tests_failed=1))["status"] == "FAIL"
    assert validate(evidence(tests_failed=1))["status"] == "FAIL"


def test_timeout_or_skipped_job_is_blocked():
    assert validate(evidence(outcome="timeout"))["status"] == "BLOCKED"
    assert validate(evidence(outcome="skipped"))["status"] == "BLOCKED"


def test_invalid_hashes_and_counts_hold():
    assert validate(evidence(diff_sha256="bad"))["status"] == "HOLD"
    assert validate(evidence(tests_passed=-1))["status"] == "HOLD"
    assert validate(evidence(test_command_sha256="bad"))["status"] == "HOLD"


def test_expected_identity_is_mandatory():
    assert validate(identity={})["status"] == "HOLD"



def test_malformed_outcome_and_boolean_schema_hold():
    assert validate(evidence(outcome={}))["status"] == "HOLD"
    assert validate(evidence(schema_version=True))["status"] == "HOLD"


def test_test_counts_must_account_for_every_collected_test():
    assert validate(evidence(tests_collected=12, tests_passed=11))["status"] == "HOLD"


def test_schema_version_must_be_an_exact_integer():
    assert validate(evidence(schema_version=1.0))["status"] == "HOLD"
