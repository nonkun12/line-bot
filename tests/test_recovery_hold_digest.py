"""Tests for the read-only Recovery AI HOLD digest."""
import json

import pytest

from scripts.recovery_hold_digest import LEGACY_REASON, build_digest, main


def test_digest_counts_legacy_and_explicit_hold_reasons():
    report = build_digest({
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {
                "legacy-task": {
                    "held": True,
                    "last_category": "unknown",
                    "updated_at": "2026-10-20T00:00:00+00:00",
                },
                "budget-task": {
                    "held": True,
                    "hold_reason": "repair_budget_exhausted",
                    "last_decision_action": "HOLD",
                    "last_decision_reason": "repair_budget_exhausted",
                    "last_category": "test_regression",
                },
                "active-task": {"held": False},
            },
        }
    })

    assert "Currently held tasks (BLOCKED / human review): **2**" in report
    assert f"| {LEGACY_REASON} | 1 |" in report
    assert "| repair_budget_exhausted | 1 |" in report
    assert "historical cause is unknown" in report
    assert "active-task" not in report


def test_digest_does_not_infer_missing_historical_reason():
    report = build_digest({
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {"held-task": {"held": True, "last_category": "unknown"}},
        }
    })
    assert LEGACY_REASON in report
    assert "non_repairable_failure" not in report


@pytest.mark.parametrize("state", [
    [],
    {},
    {"recovery_ai": []},
    {"recovery_ai": {"schema_version": 2, "tasks": {}}},
    {"recovery_ai": {"schema_version": 1, "tasks": []}},
])
def test_invalid_state_fails_closed(state):
    with pytest.raises(ValueError):
        build_digest(state)


def test_malformed_task_record_fails_closed():
    with pytest.raises(ValueError, match="record is invalid"):
        build_digest({"recovery_ai": {"schema_version": 1, "tasks": {"bad": None}}})


def test_cli_writes_report_without_mutating_input(tmp_path):
    state_path = tmp_path / "state.json"
    output_path = tmp_path / "digest.md"
    original = {
        "version": 1,
        "recovery_ai": {
            "schema_version": 1,
            "checkpoint": None,
            "tasks": {"held-task": {"held": True}},
        },
    }
    state_path.write_text(json.dumps(original), encoding="utf-8")
    before = state_path.read_bytes()

    assert main(["--state", str(state_path), "--output", str(output_path)]) == 0
    assert state_path.read_bytes() == before
    assert "held-task" in output_path.read_text(encoding="utf-8")


def test_empty_held_set_is_reported():
    report = build_digest({
        "recovery_ai": {"schema_version": 1, "tasks": {"active": {"held": False}}}
    })
    assert "Currently held tasks (BLOCKED / human review): **0**" in report
    assert "| — | — | — | — | — |" in report



def test_digest_separates_blocked_failed_and_post_resume_review_backlogs():
    report = build_digest({
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {
                "blocked-task": {
                    "held": True,
                    "consecutive_failures": 3,
                    "last_category": "timeout",
                    "last_decision_action": "HOLD",
                    "last_decision_reason": "failure_threshold_reached",
                    "updated_at": "2026-11-05T00:00:00+00:00",
                    "hold_reason": "failure_threshold_reached",
                },
                "failed-task": {
                    "held": False,
                    "consecutive_failures": 1,
                    "last_category": "test_regression",
                    "last_decision_action": "REPAIR_ONCE",
                    "last_decision_reason": "bounded_repair_attempt",
                    "updated_at": "2026-11-05T00:10:00+00:00",
                },
                "review-task": {
                    "held": False,
                    "consecutive_failures": 0,
                    "resume_requires_review": True,
                    "updated_at": "2026-11-05T00:20:00+00:00",
                },
                "healthy-task": {
                    "held": False,
                    "consecutive_failures": 0,
                },
            },
        }
    })

    assert "Currently held tasks (BLOCKED / human review): **1**" in report
    assert "Failed tasks awaiting bounded recovery or review: **1**" in report
    assert "Tasks awaiting post-resume human review: **1**" in report
    assert "| BLOCKED | blocked-task |" in report
    assert "| FAILED | failed-task |" in report
    assert "| REVIEW_REQUIRED | review-task |" in report
    assert "runtime must still enforce cooldowns" in report
    assert "healthy-task" not in report


def test_digest_does_not_treat_recovery_decision_as_execution_approval():
    report = build_digest({
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {
                "retry-task": {
                    "held": False,
                    "consecutive_failures": 1,
                    "last_category": "rate_limited",
                    "last_decision_action": "RETRY",
                    "last_decision_reason": "bounded_transient_retry",
                },
            },
        }
    })
    assert "| RETRY | 1 |" in report
    assert "not permission to execute" in report
