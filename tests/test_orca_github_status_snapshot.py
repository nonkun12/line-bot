from scripts.orca_github_status_snapshot import build_snapshot


def test_cloud_snapshot_marks_only_explicitly_attributed_streams_observed():
    payload = build_snapshot(
        [
            {"task_id": "task-a", "status": "PASS", "stream_key": "side_task_supply"},
            {"task_id": "task-b", "status": "FAIL"},
        ],
        "12345",
        "BLOCKED",
        "2026-11-05T10:00:00+00:00",
    )
    streams = {item["key"]: item for item in payload["streams"]}
    assert streams["side_task_supply"]["status"] == "observed"
    assert streams["side_task_supply"]["task_count"] == 1
    assert streams["side_task_supply"]["evidence"] == "matched_runtime_records"
    assert streams["side_self_improvement"]["status"] == "unknown"
    assert streams["side_line_full_control"]["status"] == "unknown"
    assert streams["side_media_ai"]["status"] == "unknown"
    assert payload["tasks"][1]["status"] == "FAIL"
    assert payload["dispatches"][0]["status"] == "BLOCKED"


def test_cloud_snapshot_does_not_invent_stream_attribution_for_unmapped_task():
    payload = build_snapshot(
        [{"task_id": "unmapped-task", "status": "PASS"}],
        "67890",
        "PASS",
        "2026-11-05T11:00:00+00:00",
    )
    assert all(item["status"] == "unknown" for item in payload["streams"])
    assert "stream_key" not in payload["tasks"][0]
