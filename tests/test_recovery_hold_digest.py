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
