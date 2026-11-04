from __future__ import annotations

import json
from pathlib import Path

from scripts.build_star_night_cloud_candidate import build_candidate, build_star_night_scenario
from agents.video.scenario import validate_scenario


def test_star_night_cloud_scenario_preserves_five_scene_timeline():
    scenario = build_star_night_scenario()

    assert validate_scenario(scenario) == ()
    assert scenario["title"] == "星を拾った夜 — 第1話"
    assert [scene["scene_id"] for scene in scenario["scenes"]] == [
        "SC01", "SC02", "SC03", "SC04", "SC05"
    ]
    assert sum(scene["duration_seconds"] for scene in scenario["scenes"]) == 15
    assert scenario["scenes"][2]["continuity"]["props"] == ["ITEM_LUMINA"]
    assert scenario["scenes"][3]["music_sync"]["energy"] == "high"


def test_cloud_candidate_creates_original_audio_and_review_without_claiming_video(tmp_path: Path):
    output = tmp_path / "star-night-candidate"
    result = build_candidate(output)

    assert result["status"] == "candidate_created"
    assert result["midi_status"] == "generated"
    assert result["audio_status"].startswith("synthesized_preview")
    assert result["video_status"] == "not_rendered"
    assert result["publication_authorized"] is False
    assert (output / "original_music.mid").is_file()
    assert (output / "original_music.wav").is_file()
    assert (output / "storyboard.json").is_file()
    assert not (output / "final_video.mp4").exists()

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    critic = json.loads((output / "critic_review.json").read_text(encoding="utf-8"))
    assert manifest["cloud_execution"] is True
    assert manifest["video_render_status"] == "not_rendered"
    assert manifest["artifacts"]["critic_review"] == "critic_review.json"
    assert critic["publication_authorized"] is False
