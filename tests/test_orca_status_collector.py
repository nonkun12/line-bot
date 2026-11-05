import json
from unittest.mock import patch

import pytest

from scripts.orca_status_collector import (
    CollectionError, build_streams, collect_snapshot, result_list, result_object, run_orca,
)


def envelope(result):
    return {"ok": True, "result": result}


def test_result_helpers_validate_orca_envelope():
    assert result_list(envelope({"tasks": [{"id": "t1"}]}), "tasks") == [{"id": "t1"}]
    with pytest.raises(CollectionError): result_object({"ok": True})
    with pytest.raises(CollectionError): result_list(envelope({"tasks": "bad"}), "tasks")


def test_run_orca_rejects_failed_command():
    class Completed:
        returncode = 1
        stdout = json.dumps({"ok": False, "error": {"code": "no_active_sender_terminal"}})
        stderr = ""
    with patch("scripts.orca_status_collector.subprocess.run", return_value=Completed()):
        with pytest.raises(CollectionError): run_orca(["task-list", "--json"])


def test_collector_allowlists_records_and_maps_only_explicit_stream_metadata():
    calls = []
    def fake_run(args, timeout=30):
        calls.append(args)
        if args[0] == "task-list":
            return envelope({"runId": "run1", "tasks": [
                {"id": "t1", "status": "dispatched", "stream_key": "side_task_supply", "prompt": "SECRET"}]})
        if args[0] == "worker-list":
            return envelope({"workers": [{"id": "w1", "task_id": "t1", "workerState": "ready", "argv": ["SECRET"]}]})
        if args[0] == "dispatch-show":
            return envelope({"dispatch": {"id": "d1", "status": "dispatched", "task_id": "t1", "payload": "SECRET"}})
        raise AssertionError(args)
    with patch("scripts.orca_status_collector.run_orca", side_effect=fake_run):
        snap = collect_snapshot("term-coordinator")
    assert snap["tasks"][0] == {"id": "t1", "status": "dispatched", "stream_key": "side_task_supply"}
    assert "argv" not in snap["workers"][0] and "payload" not in snap["dispatches"][0]
    stream = next(x for x in snap["streams"] if x["key"] == "side_task_supply")
    assert stream["status"] == "observed" and stream["task_count"] == 1
    assert all(x["status"] == "unknown" for x in snap["streams"] if x["key"] != "side_task_supply")
    assert calls[0] == ["task-list", "--json", "--full", "--from", "term-coordinator"]
    assert calls[1] == ["worker-list", "--json", "--full", "--include-remote"]
    assert calls[2][:3] == ["dispatch-show", "--task", "t1"]


def test_collect_snapshot_requires_terminal_handle():
    with pytest.raises(CollectionError): collect_snapshot("")


def test_build_streams_never_claims_unmatched_streams_are_active():
    streams = build_streams([], [], [])
    assert len(streams) == 5
    assert all(item["status"] == "unknown" for item in streams)
