"""Regression tests for preflight BLOCKED visibility in the Recovery AI digest."""
import pytest

from scripts.recovery_hold_digest import build_digest


def test_digest_lists_preflight_blocked_without_counting_failure():
    fingerprint = "a" * 64
    report = build_digest({
        "recovery_ai": {
            "schema_version": 1,
            "tasks": {
                "ordinary-task": {
                    "held": False,
                    "consecutive_failures": 0,
                },
            },
            "preflight_blocked": {
                fingerprint: {
                    "task_id": "blocked-before-run",
                    "reason_code": "control_tower_gate:missing_prerequisite",
                    "prerequisite_id": "setup-task",
                    "status": "PENDING_PREREQUISITE_OR_REVIEW",
                    "requires_human_review": True,
                    "first_seen_at": "2026-11-05T00:00:00+00:00",
                    "last_seen_at": "2026-11-05T01:00:00+00:00",
                    "occurrences": 2,
                },
            },
        },
    })

    assert "Persisted preflight BLOCKED events (separate from failures): **1**" in report
    assert "| PREFLIGHT_BLOCKED | blocked-before-run |" in report
    assert "control_tower_gate:missing_prerequisite" in report
    assert "| 0 | preflight | HUMAN_REVIEW_REQUIRED |" in report
    assert "never increment failure counters" in report
    assert "ordinary-task" not in report


@pytest.mark.parametrize("ledger", [
    [],
    {"not-a-fingerprint": {}},
    {"b" * 64: {"task_id": "task", "reason_code": "unsafe", "requires_human_review": True,
                 "status": "PENDING_PREREQUISITE_OR_REVIEW"}},
    {"b" * 64: {"task_id": "task", "reason_code": "control_tower_gate:ok",
                 "requires_human_review": False, "status": "PENDING_PREREQUISITE_OR_REVIEW"}},
])
def test_digest_rejects_malformed_preflight_ledger(ledger):
    with pytest.raises(ValueError):
        build_digest({"recovery_ai": {"schema_version": 1, "tasks": {}, "preflight_blocked": ledger}})
