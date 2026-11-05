import json
from unittest.mock import patch

import pytest

from scripts.orca_status_collector import (
    CollectionError,
    collect_snapshot,
    result_list,
    result_object,
    run_orca,
)


def envelope(result):
    return {"ok": True, "result": result}


def test_result_helpers_validate_orca_envelope():
    assert result_list(envelope({"tasks": [{"id": "t1"}]}), "tasks") == [{"id": "t1"}]
    with pytest.raises(CollectionError):
        result_object({"ok": True})
    with pytest.raises(CollectionError):
        result_list(envelope({"tasks": "bad"}), "tasks")


def test_run_orca_rejects_failed_command():
    class Completed:
        returncode = 1
        stdout = json.dumps({"ok": False, "error": {"code": "no_active_sender_terminal"}})
        stderr = ""

    with patch("scripts.orca_status_collector.subprocess.run", return_value=Completed()):
        with pytest.raises(CollectionError):
            run_orca(["task-list", "--json"])


def test_collect_snapshot_uses_read_only_commands_and_preserves_records():
    calls = []

    def fake_run(args, timeout=30):
        calls.append(args)
        if args[0] == "task-list":
            return envelope({"runId": "run1", "tasks": [{"id": "t1", "status": "dispatched"}]})
        if args[0] == "worker-list":
            return envelope({"workers": [{"dispatchId": "d1", "workerState": "ready"}]})
        if args[0] == "dispatch-show":
            return envelope({"dispatch": {"id": "d1", "status": "dispatched"}})
        raise AssertionError(args)

    with patch("scripts.orca_status_collector.run_orca", side_effect=fake_run):
        snapshot = collect_snapshot("term-coordinator")

    assert snapshot["run_id"] == "run1"
    assert snapshot["tasks"][0]["id"] == "t1"
    assert snapshot["workers"][0]["workerState"] == "ready"
    assert snapshot["dispatches"][0]["id"] == "d1"
    assert calls[0] == ["task-list", "--json", "--full", "--from", "term-coordinator"]
    assert calls[1] == ["worker-list", "--json", "--full", "--include-remote"]
    assert calls[2][:3] == ["dispatch-show", "--task", "t1"]
    assert not any("task-update" in call or "worker-stop" in call for call in calls)


def test_collect_snapshot_requires_terminal_handle():
    with pytest.raises(CollectionError):
        collect_snapshot("")
