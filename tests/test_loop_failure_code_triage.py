"""Regression tests for canonical fail-closed failure-code triage."""
import pytest

from core.loop_failure_codes import (
    FAILURE_CODE_CATEGORIES,
    SAFE_FAILURE_CODES,
    extract_safe_failure_code,
    failure_code_category,
    is_safe_failure_code,
)
from scripts.recovery_ai_loop_adapter import _category
from scripts.recovery_ai import RecoveryStore


def test_every_allowlisted_failure_code_has_one_canonical_category():
    assert set(SAFE_FAILURE_CODES) == set(FAILURE_CODE_CATEGORIES)
    assert all(category in {
        "invalid_task", "security_violation", "invalid_evidence"
    } for category in FAILURE_CODE_CATEGORIES.values())
    assert all(failure_code_category(code) for code in SAFE_FAILURE_CODES)


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("deterministic_anchor_not_unique:refill_cli:0", "deterministic_anchor_not_unique"),
        ("deterministic_plan_too_large: old=1201, new=1801", "deterministic_plan_too_large"),
        ("protected_file:core/secrets.py", "protected_file"),
        ("change_outside_selected_file", "change_outside_selected_file"),
        ("existing_test_modified", "existing_test_modified"),
        ("anchor_count_tests/test_x.py:2", "anchor_count"),
    ],
)
def test_deterministic_and_security_diagnostics_are_canonicalized(diagnostic, expected):
    assert extract_safe_failure_code(diagnostic) == expected


@pytest.mark.parametrize(
    "bad_code",
    [
        "unknown_code",
        "invalid_change_count ",
        "INVALID_CHANGE_COUNT",
        ["invalid_change_count"],
        {"code": "invalid_change_count"},
        True,
    ],
)
def test_present_unknown_or_malformed_code_is_invalid_evidence(bad_code):
    assert _category({
        "status": "FAIL",
        "failure_reason": "task_runtime_failed",
        "failure_code": bad_code,
    }) == "invalid_evidence"


def test_security_reason_outranks_task_plan_failure_code():
    assert _category({
        "status": "FAIL",
        "failure_reason": "outside_allowed_paths",
        "failure_code": "invalid_change_count",
    }) == "security_violation"


@pytest.mark.parametrize(
    ("status", "failure_code", "expected"),
    [
        ("FAIL", "deterministic_anchor_not_unique", "invalid_task"),
        ("BLOCKED", "protected_file", "security_violation"),
        ("STOPPED", "change_outside_selected_file", "security_violation"),
        ("FAIL", "append_only_test_anchor_or_size_invalid", "invalid_task"),
    ],
)
def test_canonical_codes_are_classified_across_failure_statuses(status, failure_code, expected):
    assert _category({
        "status": status,
        "failure_reason": "task_runtime_failed",
        "failure_code": failure_code,
    }) == expected


def test_blocked_or_stopped_without_machine_evidence_fails_closed():
    assert _category({"status": "BLOCKED", "failure_reason": "blocked"}) == "invalid_evidence"
    assert _category({"status": "STOPPED", "failure_reason": "stop_requested"}) == "invalid_evidence"


def test_original_hold_category_survives_later_failure(tmp_path):
    store = RecoveryStore(tmp_path / "recovery.json")
    first = store.record_failure("task-held", "security_violation")
    assert first.action == "HOLD"
    before = store.task_status("task-held")
    second = store.record_failure("task-held", "unknown")
    after = store.task_status("task-held")

    assert second.action == "HOLD"
    assert after["last_category"] == "unknown"
    assert after["hold_category"] == "security_violation"
    assert after["hold_reason"] == before["hold_reason"]


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("change_path_outside_root:/tmp/escape.py", "change_path_outside_root"),
        ("self_improvement_policy:blocked", "self_improvement_policy"),
        ("required_regression_test_missing:tests/test_x.py", "required_regression_test_missing"),
        ("existing_test_missing:tests/test_x.py", "existing_test_missing"),
        ("operational_validation_plan_invalid:SyntaxError", "operational_validation_plan_invalid"),
        ("deterministic target unavailable or disallowed: tests/x.py", "deterministic_target_unavailable_or_disallowed"),
        ("deterministic target mismatch: expected tests/x.py", "deterministic_target_mismatch"),
        ("manager could not select a safe target", "manager_could_not_select_safe_target"),
        ("manager selection missing", "manager_selection_missing"),
        ("invalid_change", "invalid_change"),
        ("invalid_old_new", "invalid_old_new"),
        ("no_op_change", "no_op_change"),
        ("diff_marker_in_replacement", "diff_marker_in_replacement"),
        ("change_too_large", "change_too_large"),
        ("invalid_plan", "invalid_plan"),
        ("duplicate_change_path", "duplicate_change_path"),
        ("change_target_unreadable", "change_target_unreadable"),
    ],
)
def test_reported_runtime_diagnostics_are_all_canonicalized(diagnostic, expected):
    assert extract_safe_failure_code(diagnostic) == expected
    assert failure_code_category(expected) in {"invalid_task", "security_violation"}


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("invalid_change_count then protected_file:core/x.py", "protected_file"),
        ("sha_mismatch then anchor_count_tests/x.py:1", "sha_mismatch"),
        ("protected_file then nonce_mismatch", "nonce_mismatch"),
        ("change_outside_selected_file then deterministic_plan_too_large", "change_outside_selected_file"),
    ],
)
def test_security_diagnostic_precedence_is_deterministic(diagnostic, expected):
    assert extract_safe_failure_code(diagnostic) == expected


def test_legacy_hold_category_is_never_inferred_from_last_category(tmp_path):
    store = RecoveryStore(tmp_path / "legacy.json")
    store.path.write_text(
        '{"schema_version":1,"tasks":{"legacy":{"held":true,"last_category":"unknown","consecutive_failures":2,"fingerprints":[]}},"checkpoint":null}',
        encoding="utf-8",
    )
    decision = store.record_failure("legacy", "unknown")
    assert decision.action == "HOLD"
    assert store.task_status("legacy")["hold_category"] == "legacy_hold_category_unavailable"
