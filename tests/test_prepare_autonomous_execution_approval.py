import hashlib
import json

import pytest

from scripts.prepare_autonomous_execution_approval import prepare_approval_manifest, main


def fixtures():
    task = {
        "id": "review-coverage-gap-a1b2c3d4e5",
        "instruction": "Add one focused regression test.",
        "allowed_paths": ["tests/test_example.py"],
        "execution_approved": True,
    }
    queue = {
        "version": 1, "max_tasks_per_run": 1,
        "tasks": [{key: task[key] for key in ("id", "instruction", "allowed_paths")}],
    }
    catalog = {"version": 1, "tasks": [task]}
    state = {
        "version": 1, "completed": [],
        "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": {}},
    }
    return queue, catalog, state, task


def test_manifest_binds_exact_approved_task_and_grants_no_authority():
    queue, catalog, state, task = fixtures()
    manifest = prepare_approval_manifest(
        queue, catalog, state, task_id=task["id"], base_sha="a" * 40,
    )
    assert manifest["status"] == "READY_FOR_HUMAN_DISPATCH"
    assert manifest["task_id"] == task["id"]
    assert manifest["base_sha"] == "a" * 40
    assert manifest["instruction_sha256"] == hashlib.sha256(task["instruction"].encode()).hexdigest()
    assert manifest["allowed_paths_sha256"] == hashlib.sha256(
        json.dumps(task["allowed_paths"], separators=(",", ":")).encode()
    ).hexdigest()
    assert manifest["max_tasks"] == 1
    assert manifest["execution_authorized"] is False
    assert manifest["human_dispatch_required"] is True
    assert manifest["merge_authorized"] is False
    assert manifest["deploy_authorized"] is False


@pytest.mark.parametrize("mutation", ["unapproved", "held", "review", "completed", "definition", "multi_queue"])
def test_manifest_fails_closed_for_ineligible_or_ambiguous_task(mutation):
    queue, catalog, state, task = fixtures()
    if mutation == "unapproved":
        catalog["tasks"][0]["execution_approved"] = False
    elif mutation == "held":
        state["recovery_ai"]["tasks"][task["id"]] = {"held": True}
    elif mutation == "review":
        state["recovery_ai"]["tasks"][task["id"]] = {"resume_requires_review": True}
    elif mutation == "completed":
        state["completed"].append(task["id"])
    elif mutation == "definition":
        queue["tasks"][0]["instruction"] = "different instruction"
    elif mutation == "multi_queue":
        queue["tasks"].append(dict(queue["tasks"][0]))
    with pytest.raises(ValueError):
        prepare_approval_manifest(queue, catalog, state, task_id=task["id"], base_sha="a" * 40)


def test_manifest_cli_writes_atomic_read_only_document(tmp_path):
    queue, catalog, state, task = fixtures()
    q, c, st, out = [tmp_path / name for name in ("queue.json", "catalog.json", "state.json", "manifest.json")]
    for path, value in ((q, queue), (c, catalog), (st, state)):
        path.write_text(json.dumps(value), encoding="utf-8")
    assert main([
        "--queue", str(q), "--catalog", str(c), "--state", str(st),
        "--task-id", task["id"], "--base-sha", "a" * 40, "--output", str(out),
    ]) == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["execution_authorized"] is False
    assert json.loads(c.read_text(encoding="utf-8")) == catalog
    assert json.loads(q.read_text(encoding="utf-8")) == queue
    assert json.loads(st.read_text(encoding="utf-8")) == state


def test_manifest_rejects_bad_base_sha_and_non_test_path():
    queue, catalog, state, task = fixtures()
    with pytest.raises(ValueError, match="base SHA"):
        prepare_approval_manifest(queue, catalog, state, task_id=task["id"], base_sha="not-a-sha")
    catalog["tasks"][0]["allowed_paths"] = ["scripts/unsafe.py"]
    queue["tasks"][0]["allowed_paths"] = ["scripts/unsafe.py"]
    with pytest.raises(ValueError, match="allowlisted test path"):
        prepare_approval_manifest(queue, catalog, state, task_id=task["id"], base_sha="a" * 40)
