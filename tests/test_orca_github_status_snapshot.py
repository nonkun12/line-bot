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
    assert streams["side_core_vocabulary"]["status"] == "unknown"
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


def test_cloud_status_publisher_is_optional_and_non_blocking():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "distributed-autonomous-loop.yml"
    ).read_text(encoding="utf-8")
    step = workflow.split("      - name: Publish cloud Orca runtime snapshot to Render", 1)[1].split("      - name:", 1)[0]
    assert "secrets.ORCA_STATUS_URL" in step
    assert "secrets.ORCA_STATUS_SECRET" in step
    assert "continue-on-error: true" in step
    assert "scripts.orca_github_status_snapshot" in step
    assert "scripts/orca_status_publisher.py" in step


def test_cloud_snapshot_attributes_core_vocabulary_only_with_explicit_stream_metadata():
    payload = build_snapshot(
        [{"task_id": "english-batch-1", "status": "NO_CHANGE", "stream_key": "side_core_vocabulary"}],
        "13579",
        "PASS",
        "2026-11-05T12:00:00+00:00",
    )
    streams = {item["key"]: item for item in payload["streams"]}
    assert streams["side_core_vocabulary"]["status"] == "observed"
    assert streams["side_core_vocabulary"]["task_count"] == 1
    assert payload["tasks"][0]["stream_key"] == "side_core_vocabulary"


def test_cloud_snapshot_includes_only_sanitized_rea_artifact_metadata():
    payload = build_snapshot(
        [{
            "task_id": "task-rea",
            "status": "BLOCKED",
            "rea_artifact": {
                "status": "HOLD",
                "reason_code": "risk_unknown",
                "evidence_sha256": "a" * 64,
                "execution_authorized": False,
                "patch_authorized": False,
                "hold_clear_authorized": False,
                "merge_deploy_authorized": False,
                "raw_diff": "must not leak",
            },
        }],
        "24680",
        "BLOCKED",
        "2026-11-05T13:00:00+00:00",
    )
    task = payload["tasks"][0]
    assert task["rea_artifact_status"] == "HOLD"
    assert task["rea_artifact_reason_code"] == "risk_unknown"
    assert task["rea_artifact_evidence_sha256"] == "a" * 64
    assert task["rea_artifact_execution_authorized"] is False
    assert task["rea_artifact_merge_deploy_authorized"] is False
    assert "raw_diff" not in task
