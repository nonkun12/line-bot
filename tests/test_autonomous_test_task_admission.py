from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.autonomous_task_target_allowlist import TARGETS
from scripts.autonomous_test_task_admission import build_policy_admission


def _inputs(tmp_path: Path):
    source_path, test_path = TARGETS[0]
    source = tmp_path / source_path
    test = tmp_path / test_path
    source.parent.mkdir(parents=True, exist_ok=True)
    test.parent.mkdir(parents=True, exist_ok=True)
    source_text = "def target(value):\n    return value\n"
    test_text = "def test_existing():\n    assert True\n"
    source.write_text(source_text, encoding="utf-8")
    test.write_text(test_text, encoding="utf-8")
    task_id = "review-coverage-gap-" + hashlib.sha256(
        f"{source_path}:target".encode("utf-8")
    ).hexdigest()[:10]
    fingerprint = hashlib.sha256(
        f"{source_path}\0target\0{1}\0"
        f"{hashlib.sha256(source_text.encode()).hexdigest()}\0"
        f"{hashlib.sha256(test_text.encode()).hexdigest()}".encode()
    ).hexdigest()
    report = {
        "status": "REVIEW_REQUIRED",
        "candidate_count": 1,
        "safety": {
            "read_only": True,
            "requires_human_review": True,
            "candidates_executable": False,
        },
        "candidates": [{
            "id": task_id,
            "target_test": test_path,
            "source_function": "target",
            "evidence": f"{source_path}:1",
            "fingerprint": fingerprint,
            "status": "REVIEW_REQUIRED",
        }],
    }
    queue = {"max_tasks_per_run": 4, "tasks": []}
    catalog = {"max_additions_per_run": 4, "tasks": []}
    state = {
        "completed": [],
        "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": {}},
    }
    return report, queue, catalog, state, task_id, test_path


def test_admits_one_verified_test_only_candidate_to_run_local_inputs(tmp_path):
    report, queue, catalog, state, task_id, test_path = _inputs(tmp_path)
    result = build_policy_admission(report, queue, catalog, state, tmp_path)

    assert result["report"]["status"] == "POLICY_ADMITTED"
    assert result["report"]["admitted_task_id"] == task_id
    assert result["queue"]["max_tasks_per_run"] == 1
    assert [item["id"] for item in result["queue"]["tasks"]] == [task_id]
    assert result["catalog"]["tasks"][0]["execution_approved"] is True
    assert result["catalog"]["tasks"][0]["allowed_paths"] == [test_path]
    assert result["review_report"]["status"] == "NO_SAFE_CANDIDATE"
    assert catalog["tasks"] == []
    assert queue["tasks"] == []
    assert state["completed"] == []
    assert result["report"]["persistent_catalog_modified"] is False
    assert result["report"]["durable_state_modified"] is False


def test_existing_queue_prevents_policy_admission(tmp_path):
    report, queue, catalog, state, task_id, _ = _inputs(tmp_path)
    queue["tasks"] = [{"id": "already-approved", "instruction": "run", "allowed_paths": ["tests/test_agent_events.py"]}]
    result = build_policy_admission(report, queue, catalog, state, tmp_path)

    assert result["report"]["status"] == "POLICY_SKIPPED"
    assert result["report"]["reason"] == "existing_approved_queue_has_priority"
    assert result["queue"]["tasks"][0]["id"] == "already-approved"
    assert catalog["tasks"] == []


def test_recovery_record_prevents_re_admission(tmp_path):
    report, queue, catalog, state, task_id, _ = _inputs(tmp_path)
    state["recovery_ai"]["tasks"][task_id] = {"held": True, "resume_requires_review": False}
    result = build_policy_admission(report, queue, catalog, state, tmp_path)

    assert result["report"]["status"] == "POLICY_SKIPPED"
    assert result["report"]["reason"] == "no_candidate_passed_current_source_and_state_validation"
    assert result["queue"]["tasks"] == []
    assert catalog["tasks"] == []


def test_stale_fingerprint_is_not_admitted(tmp_path):
    report, queue, catalog, state, _, _ = _inputs(tmp_path)
    report["candidates"][0]["fingerprint"] = "0" * 64
    result = build_policy_admission(report, queue, catalog, state, tmp_path)

    assert result["report"]["status"] == "POLICY_SKIPPED"
    assert result["queue"]["tasks"] == []
    assert catalog["tasks"] == []
