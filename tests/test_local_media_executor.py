from __future__ import annotations

import json

import pytest

from agents.media.local_executor import (
    EXECUTOR_ID,
    OPERATION,
    execute_local_media_job,
)
from agents.video.scenario import build_scenario


def _job(job_id: int = 42) -> dict:
    return {"id": job_id, "job_type": "goal_child", "claim_token": "x" * 32}


def _payload() -> dict:
    return {
        "executor": EXECUTOR_ID,
        "operation": OPERATION,
        "scenario": build_scenario("夜明けの街", duration_seconds=15, scene_count=3),
    }


def test_local_executor_creates_hashed_bundle_under_fixed_root(tmp_path):
    output = execute_local_media_job(_job(), _payload(), output_root=tmp_path)
    evidence = output["evidence"]

    assert all(item["status"] == "PASS" for item in evidence["checks"])
    assert evidence["output_directory"] == str(tmp_path.resolve() / "goal-child-42")
    assert set(evidence["artifact_sha256"]) == {
        "scenario", "storyboard", "shot_list", "music_plan", "midi", "audio_preview", "video_edit_decision_list"
    }
    assert all(len(value) == 64 for value in evidence["artifact_sha256"].values())
    bundle = tmp_path / "goal-child-42"
    storyboard = json.loads((bundle / "storyboard.json").read_text(encoding="utf-8"))
    shot_list = json.loads((bundle / "shot_list.json").read_text(encoding="utf-8"))
    assert storyboard["schema_version"] == "video-storyboard.v1"
    assert shot_list["schema_version"] == "video-shot-list.v1"
    assert shot_list["external_assets_downloaded"] is False
    assert shot_list["render_status"] == "not_rendered"
    assert sum(shot["duration_seconds"] for shot in shot_list["shots"]) == 15
    receipt = json.loads((bundle / "executor_receipt.json").read_text())
    assert receipt["publication"] == "not_performed"
    assert receipt["video_render_status"] == "not_rendered"


def test_local_executor_rejects_non_goal_job(tmp_path):
    with pytest.raises(PermissionError):
        execute_local_media_job(
            {"id": 42, "job_type": "generic", "claim_token": "x" * 32},
            _payload(),
            output_root=tmp_path,
        )


def test_local_executor_requires_claim_token(tmp_path):
    job = _job()
    job["claim_token"] = ""
    with pytest.raises(PermissionError):
        execute_local_media_job(job, _payload(), output_root=tmp_path)


def test_local_executor_requires_explicit_executor_type(tmp_path):
    payload = _payload()
    payload["executor"] = "shell"
    with pytest.raises(PermissionError):
        execute_local_media_job(_job(), payload, output_root=tmp_path)


def test_local_executor_rejects_payload_controlled_output_paths(tmp_path):
    payload = _payload()
    payload["output_path"] = "../../outside"
    output = execute_local_media_job(_job(), payload, output_root=tmp_path)
    assert output["evidence"]["output_directory"] == str(tmp_path.resolve() / "goal-child-42")


def test_local_executor_reuses_only_an_integrity_verified_existing_bundle(tmp_path):
    first = execute_local_media_job(_job(), _payload(), output_root=tmp_path)
    second = execute_local_media_job(_job(), _payload(), output_root=tmp_path)
    assert second["result"] == first["result"]
    assert second["evidence"]["artifact_sha256"] == first["evidence"]["artifact_sha256"]


def test_local_executor_rejects_invalid_scenario_before_creating_output(tmp_path):
    payload = _payload()
    payload["scenario"]["schema_version"] = "invalid"
    with pytest.raises(ValueError, match="invalid production scenario"):
        execute_local_media_job(_job(), payload, output_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_local_executor_holds_on_partial_existing_output(tmp_path):
    partial = tmp_path / "goal-child-42"
    partial.mkdir()
    (partial / "scenario.json").write_text("partial", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no safe receipt"):
        execute_local_media_job(_job(), _payload(), output_root=tmp_path)
    assert (partial / "scenario.json").read_text(encoding="utf-8") == "partial"
