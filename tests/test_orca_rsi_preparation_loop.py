import json

from scripts.orca_rsi_preparation_loop import _task_digest, build_report


def _catalog():
    return {
        "version": 1,
        "max_additions_per_run": 4,
        "tasks": [
            {
                "id": "safe-regression-task",
                "instruction": "Add one isolated regression test.",
                "allowed_paths": ["tests/test_example.py"],
                "execution_approved": True,
            },
            {
                "id": "unapproved-task",
                "instruction": "Do not execute until separately approved.",
                "allowed_paths": ["tests/test_other.py"],
                "execution_approved": False,
            },
        ],
    }


def _state():
    return {
        "schema_version": 1,
        "revision": 4,
        "global_hold": False,
        "emergency_stop": False,
        "tasks": [],
        "active_lease": None,
    }


def test_preparation_loop_identifies_candidate_without_authorizing_execution():
    report = build_report(_catalog(), _state())
    assert report["status"] == "READY_FOR_HUMAN_REVIEW"
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["task_id"] == "safe-regression-task"
    assert len(candidate["task_digest"]) == 64
    assert candidate["catalog_candidate_flag"] is True
    assert candidate["execution_approved"] is False
    assert candidate["human_execution_approval_required"] is True
    assert candidate["dispatch_authorized"] is False
    assert report["worker_started"] is False
    assert report["queue_written"] is False
    assert report["execution_authorized"] is False


def test_preparation_loop_respects_global_hold_and_does_not_dispatch():
    state = _state()
    state["global_hold"] = True
    report = build_report(_catalog(), state)
    assert report["status"] == "BLOCKED"
    assert "global_hold_active" in report["blockers"]
    assert report["candidate_count"] == 1
    assert report["decision"] == "wait_without_dispatch"
    assert report["worker_started"] is False


def test_preparation_loop_blocks_emergency_stop_and_existing_lease():
    state = _state()
    state["emergency_stop"] = True
    state["active_lease"] = {"worker_id": "already-running"}
    report = build_report(_catalog(), state)
    assert report["status"] == "BLOCKED"
    assert "emergency_stop_active" in report["blockers"]
    assert "worker_lease_already_active" in report["blockers"]


def test_preparation_loop_blocks_when_no_approved_candidate_exists():
    catalog = _catalog()
    catalog["tasks"] = [dict(catalog["tasks"][1])]
    report = build_report(catalog, _state())
    assert report["status"] == "BLOCKED"
    assert "no_approved_unqueued_catalog_task" in report["blockers"]


def test_preparation_loop_blocks_duplicate_or_malformed_catalog_tasks():
    catalog = _catalog()
    catalog["tasks"].append(dict(catalog["tasks"][0]))
    try:
        build_report(catalog, _state())
    except ValueError as exc:
        assert str(exc) == "catalog_task_invalid"
    else:
        raise AssertionError("duplicate catalog task IDs must be rejected")


def test_task_digest_binds_approval_and_all_catalog_metadata():
    task = _catalog()["tasks"][0]
    original = _task_digest(task)
    changed = dict(task, execution_approved=False)
    assert _task_digest(changed) != original
    changed = dict(task, review_policy="independent-review-required")
    assert _task_digest(changed) != original


def test_catalog_execution_approved_flag_never_becomes_human_execution_authority():
    report = build_report(_catalog(), _state())
    candidate = report["candidates"][0]
    assert report["catalog_candidate_flag_count"] == 1
    assert "execution_approved_count" not in report
    assert candidate["catalog_candidate_flag"] is True
    assert candidate["execution_approved"] is False
    assert candidate["human_execution_approval_required"] is True
    assert report["execution_authorized"] is False
