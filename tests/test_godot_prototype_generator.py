from __future__ import annotations
import json
import pytest
from agents.media.godot_prototype_generator import build_godot_project_files, generate_godot_project

def sample_design():
    return {
        "schema_version": "godot-game-design.v1",
        "approved_candidate_id": "candidate-1",
        "engine": "Godot", "target_platform": "desktop",
        "safety_policy": {"design_only": True, "automatic_publication": False},
        "scene_mapping": [
            {"scene_id": "opening", "story_intent": "A quiet beginning",
             "player_feedback": {"visual": "Blue light", "audio": "Soft motif"}},
            {"scene_id": "ending", "story_intent": "A hopeful resolution",
             "player_feedback": {"visual": "Warm light", "audio": "Resolved motif"}},
        ],
    }

def test_builds_runnable_godot_project_file_set():
    files = build_godot_project_files(sample_design())
    assert {"project.godot", "scenes/main.tscn", "scripts/main.gd",
            "scripts/audio_controller.gd", "scripts/visual_controller.gd", "data/story.json"} <= set(files)
    story = json.loads(files["data/story.json"])
    assert [item["scene_id"] for item in story["scenes"]] == ["opening", "ending"]
    assert "request_scene_cue" in files["scripts/main.gd"]
    assert "signal scene_cue_requested" in files["scripts/audio_controller.gd"]

def test_generation_creates_new_project_without_media_or_network(tmp_path):
    destination = tmp_path / "new-game"
    result = generate_godot_project(sample_design(), destination)
    assert result["status"] == "CREATED"
    assert result["file_count"] == 7
    assert result["assets_copied"] is False and result["network_used"] is False
    assert (destination / "project.godot").is_file()
    assert (destination / "data/story.json").is_file()

def test_existing_destination_is_never_overwritten(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        generate_godot_project(sample_design(), destination)
    assert sentinel.read_text(encoding="utf-8") == "preserve"

@pytest.mark.parametrize("mutate", [
    lambda value: value.update(schema_version="wrong"),
    lambda value: value.update(approved_candidate_id=""),
    lambda value: value.update(engine="Unity"),
    lambda value: value.update(safety_policy={"design_only": False, "automatic_publication": False}),
    lambda value: value.update(scene_mapping=[]),
    lambda value: value.update(scene_mapping=[{"scene_id": "../escape", "story_intent": "x"}]),
])
def test_rejects_invalid_design(mutate):
    value = sample_design()
    mutate(value)
    with pytest.raises(ValueError):
        build_godot_project_files(value)

def test_rejects_duplicate_scene_ids():
    value = sample_design()
    value["scene_mapping"][1]["scene_id"] = "opening"
    with pytest.raises(ValueError):
        build_godot_project_files(value)

def test_deterministic_file_contents():
    assert build_godot_project_files(sample_design()) == build_godot_project_files(sample_design())

def approved_manifest():
    return {
        "schema_version": "godot-approved-assets.v1",
        "human_approved": True,
        "publication_authorized": False,
        "scenes": [{
            "scene_id": "opening",
            "approval_note": "Original locally created assets reviewed by the user",
            "audio_path": "res://assets/opening.ogg",
            "image_path": "res://assets/opening.png",
            "video_path": "res://assets/opening.ogv",
        }],
    }

def test_approved_local_assets_are_bound_to_matching_story_scene():
    files = build_godot_project_files(sample_design(), approved_manifest())
    story = json.loads(files["data/story.json"])
    opening = story["scenes"][0]
    assert opening["audio_path"] == "res://assets/opening.ogg"
    assert opening["image_path"] == "res://assets/opening.png"
    assert opening["video_path"] == "res://assets/opening.ogv"
    assert "player.play()" in files["scripts/audio_controller.gd"]
    assert "video_node.play()" in files["scripts/visual_controller.gd"]

@pytest.mark.parametrize("changes", [
    {"human_approved": False},
    {"publication_authorized": True},
    {"scenes": [{"scene_id": "unknown", "approval_note": "approved", "audio_path": "res://assets/a.ogg"}]},
    {"scenes": [{"scene_id": "opening", "approval_note": "", "audio_path": "res://assets/a.ogg"}]},
    {"scenes": [{"scene_id": "opening", "approval_note": "approved", "audio_path": "res://outside/a.ogg"}]},
    {"scenes": [{"scene_id": "opening", "approval_note": "approved", "audio_path": "res://assets/../secret.ogg"}]},
    {"scenes": [{"scene_id": "opening", "approval_note": "approved", "audio_path": "res://assets/a.exe"}]},
])
def test_rejects_unapproved_or_unsafe_asset_manifest(changes):
    manifest = approved_manifest()
    manifest.update(changes)
    with pytest.raises(ValueError):
        build_godot_project_files(sample_design(), manifest)
