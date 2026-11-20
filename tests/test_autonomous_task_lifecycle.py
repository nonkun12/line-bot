import json

from scripts.distributed_loop_execution_approval import authorize_one_task
from scripts.prepare_autonomous_execution_approval import prepare_approval_manifest
from scripts.self_improvement_state import append_cycle_memory, append_loop_results


def test_registered_approved_task_flows_through_dispatch_gate_and_feedback(tmp_path, monkeypatch):
    task = {
        "id": "review-coverage-gap-1234567890",
        "instruction": "Add one focused regression test.",
        "allowed_paths": ["tests/test_example.py"],
        "execution_approved": True,
    }
    catalog = {"version": 1, "tasks": [task]}
    queue = {
        "version": 1, "max_tasks_per_run": 1,
        "tasks": [{key: task[key] for key in ("id", "instruction", "allowed_paths")}],
    }
    state = {
        "version": 1, "completed": [],
        "recovery_ai": {"schema_version": 1, "tasks": {}, "checkpoint": {}},
    }
    base_sha, produced_sha = "a" * 40, "b" * 40

    manifest = prepare_approval_manifest(
        queue, catalog, state, task_id=task["id"], base_sha=base_sha,
    )
    assert manifest["execution_authorized"] is False

    event = {
        "sender": {"login": "nonkun12"},
        "repository": {"full_name": "nonkun12/line-bot"},
        "inputs": {
            "execution_approval": "APPROVE_EXECUTION",
            "mode": "normal",
            "approval_task_id": manifest["task_id"],
            "approval_instruction_sha256": manifest["instruction_sha256"],
            "approval_allowed_paths_sha256": manifest["allowed_paths_sha256"],
            "approval_base_sha": manifest["base_sha"],
        },
    }
    queue_path, event_path, catalog_path = (
        tmp_path / "queue.json", tmp_path / "event.json", tmp_path / "catalog.json"
    )
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    event_path.write_text(json.dumps(event), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    approval = authorize_one_task(
        queue_path, event_path, catalog_path, base_sha=base_sha,
        ref="refs/heads/main", actor="nonkun12", repository="nonkun12/line-bot",
    )
    assert approval["status"] == "PASS"
    assert approval["authorized_task_count"] == 1
    assert [row["id"] for row in json.loads(queue_path.read_text())["tasks"]] == [task["id"]]

    results, history = tmp_path / "results.jsonl", tmp_path / "history.jsonl"
    results.write_text(json.dumps({
        "task_id": task["id"], "status": "PASS", "exit_code": 0,
        "base_sha": base_sha, "produced_sha": produced_sha,
    }) + "\n", encoding="utf-8")
    assert append_loop_results(
        history, results, catalog_path, publish_outcome="success", state_outcome="success",
    ) == 1
    assert append_cycle_memory(
        history, results, catalog_path, publish_outcome="success",
        state_outcome="success", cycle_id="70001",
    ) == 1
    rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert any(row.get("kind") == "success" and row.get("task_id") == task["id"] for row in rows)
    assert any(row.get("record_type") == "cycle_memory" and row.get("outcome") == "PASS" for row in rows)


def test_failed_publish_or_state_gate_never_teaches_task_success(tmp_path):
    task = {
        "id": "review-coverage-gap-1234567890",
        "instruction": "Add one focused regression test.",
        "allowed_paths": ["tests/test_example.py"],
        "execution_approved": True,
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
    results, history = tmp_path / "results.jsonl", tmp_path / "history.jsonl"
    results.write_text(json.dumps({
        "task_id": task["id"], "status": "PASS", "exit_code": 0,
    }) + "\n", encoding="utf-8")
    assert append_loop_results(
        history, results, catalog, publish_outcome="failure", state_outcome="success",
    ) == 0
    assert append_cycle_memory(
        history, results, catalog, publish_outcome="failure",
        state_outcome="success", cycle_id="70002",
    ) == 0
    assert not history.exists()
