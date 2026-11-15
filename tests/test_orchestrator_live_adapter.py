from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.orchestrator_live_adapter import (
    SnapshotError,
    build_live_snapshot,
    build_snapshot_from_paths,
)


NOW = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)


def task(task_id="task-a"):
    return {
        "id": task_id,
        "instruction": "Read-only regression task",
        "allowed_paths": ["tests/test_example.py"],
    }


def state(*, completed=None, recovery_tasks=None):
    return {
        "version": 1,
        "completed": list(completed or []),
        "recovery_ai": {
            "schema_version": 1,
            "tasks": dict(recovery_tasks or {}),
        },
    }


def evidence_files(tmp_path: Path, *, hold=False, budget=True, observed_at="2026-11-15T07:30:00+00:00"):
    hold_path = tmp_path / "hold.json"
    hold_path.write_text(json.dumps({
        "schema_version": 1,
        "global_hold": hold,
        "source": "test-control-plane",
        "observed_at": observed_at,
    }), encoding="utf-8")
    budget_path = tmp_path / "budget.json"
    if budget:
        budget_path.write_text(json.dumps({
            "schema_version": 1,
            "source": "test-usage-ledger",
            "observed_at": observed_at,
            "limit_minutes": 2000,
            "consumed_minutes": 100,
            "reserved_minutes": 50,
        }), encoding="utf-8")
    return hold_path, budget_path if budget else None


def test_missing_hold_and_budget_evidence_blocks_without_execution():
    snapshot = build_live_snapshot(
        {"tasks": [task()]},
        {"tasks": [task()]},
        state(),
        now=NOW,
    )
    assert snapshot["status"] == "BLOCKED"
    assert "global_hold_state_missing" in snapshot["reasons"]
    assert "budget_evidence_missing" in snapshot["reasons"]
    assert snapshot["candidate_ids"] == []
    assert snapshot["execution_authorized"] is False
    assert snapshot["approval_evidence_verified"] is False
    assert snapshot["budget_evidence_verified"] is False
    assert snapshot["dispatch_performed"] is False


def test_well_formed_but_unauthenticated_evidence_never_unblocks_plan(tmp_path):
    hold_path, budget_path = evidence_files(tmp_path)
    snapshot = build_live_snapshot(
        {"tasks": [task()]},
        {"tasks": [task()]},
        state(),
        hold_state_path=hold_path,
        budget_evidence_path=budget_path,
        now=NOW,
    )
    assert snapshot["status"] == "BLOCKED"
    assert snapshot["candidate_ids"] == []
    assert snapshot["potential_candidate_count"] == 1
    assert snapshot["execution_authorized"] is False
    assert snapshot["approval_evidence_verified"] is False
    assert snapshot["budget_evidence_verified"] is False
    assert snapshot["global_hold"]["verified"] is False
    assert snapshot["budget"]["verified"] is False
    assert "global_hold_unverified" in snapshot["reasons"]
    assert "budget_evidence_unverified" in snapshot["reasons"]
    assert "approval_evidence_unverified" in snapshot["reasons"]


def test_global_hold_blocks_even_with_valid_budget(tmp_path):
    hold_path, budget_path = evidence_files(tmp_path, hold=True)
    snapshot = build_live_snapshot(
        {"tasks": [task()]},
        {"tasks": [task()]},
        state(),
        hold_state_path=hold_path,
        budget_evidence_path=budget_path,
        now=NOW,
    )
    assert snapshot["status"] == "BLOCKED"
    assert snapshot["candidate_ids"] == []
    assert "global_hold_active" in snapshot["reasons"]
    assert snapshot["execution_authorized"] is False


@pytest.mark.parametrize(
    ("durable", "expected"),
    [
        (state(completed=["task-a"]), "completed"),
        (state(recovery_tasks={"task-a": {"held": True}}), "held"),
        (state(recovery_tasks={"task-a": {"resume_requires_review": True}}), "review_required"),
    ],
)
def test_completed_held_and_review_required_tasks_are_never_candidates(
    tmp_path, durable, expected
):
    hold_path, budget_path = evidence_files(tmp_path)
    snapshot = build_live_snapshot(
        {"tasks": [task()]},
        {"tasks": [task()]},
        durable,
        hold_state_path=hold_path,
        budget_evidence_path=budget_path,
        now=NOW,
    )
    assert snapshot["tasks"][0]["state"] == expected
    assert snapshot["candidate_ids"] == []
    assert snapshot["status"] == "BLOCKED"
    assert snapshot["execution_authorized"] is False



def test_completed_task_with_review_flag_stays_terminal_and_is_counted(tmp_path):
    hold_path, budget_path = evidence_files(tmp_path)
    snapshot = build_live_snapshot(
        {"tasks": [task()]},
        {"tasks": [task()]},
        state(
            completed=["task-a"],
            recovery_tasks={"task-a": {"resume_requires_review": True}},
        ),
        hold_state_path=hold_path,
        budget_evidence_path=budget_path,
        now=NOW,
    )
    assert snapshot["tasks"][0]["state"] == "completed"
    assert snapshot["tasks"][0]["resume_requires_review"] is True
    assert snapshot["sources"]["catalog_review_required_count"] == 1
    assert snapshot["candidate_ids"] == []
    assert snapshot["status"] == "NO_TASK"

def test_queue_catalog_definition_mismatch_is_rejected():
    queued = task()
    catalogued = {**task(), "instruction": "Different instruction"}
    with pytest.raises(SnapshotError, match="queue_catalog_definition_mismatch"):
        build_live_snapshot(
            {"tasks": [queued]},
            {"tasks": [catalogued]},
            state(),
            now=NOW,
        )


def test_stale_budget_evidence_fails_closed(tmp_path):
    hold_path, budget_path = evidence_files(
        tmp_path, observed_at="2026-11-15T05:00:00+00:00"
    )
    hold_doc = json.loads(hold_path.read_text(encoding="utf-8"))
    hold_doc["observed_at"] = "2026-11-15T07:30:00+00:00"
    hold_path.write_text(json.dumps(hold_doc), encoding="utf-8")
    with pytest.raises(SnapshotError, match="budget_stale"):
        build_live_snapshot(
            {"tasks": [task()]},
            {"tasks": [task()]},
            state(),
            hold_state_path=hold_path,
            budget_evidence_path=budget_path,
            now=NOW,
        )


def test_empty_queue_with_valid_evidence_is_no_task(tmp_path):
    hold_path, budget_path = evidence_files(tmp_path)
    snapshot = build_live_snapshot(
        {"tasks": []},
        {"tasks": [task()]},
        state(),
        hold_state_path=hold_path,
        budget_evidence_path=budget_path,
        now=NOW,
    )
    assert snapshot["status"] == "NO_TASK"
    assert snapshot["candidate_ids"] == []
    assert snapshot["sources"]["runtime_queue_count"] == 0
    assert snapshot["execution_authorized"] is False


def test_path_adapter_emits_source_hashes_and_fail_closed_status(tmp_path):
    queue_path = tmp_path / "queue.json"
    catalog_path = tmp_path / "catalog.json"
    state_path = tmp_path / "state.json"
    queue_path.write_text(json.dumps({"tasks": [task()]}), encoding="utf-8")
    catalog_path.write_text(json.dumps({"tasks": [task()]}), encoding="utf-8")
    state_path.write_text(json.dumps(state()), encoding="utf-8")
    snapshot = build_snapshot_from_paths(queue_path, catalog_path, state_path, now=NOW)
    assert len(snapshot["sources"]["runtime_queue_sha256"]) == 64
    assert len(snapshot["sources"]["task_catalog_sha256"]) == 64
    assert len(snapshot["sources"]["durable_state_sha256"]) == 64
    assert snapshot["status"] == "BLOCKED"
    assert snapshot["execution_authorized"] is False
