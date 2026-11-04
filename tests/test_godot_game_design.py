import pytest

from agents.media.godot_game_design import build_story_driven_godot_design


def _scenario():
    return {
        "schema_version": "video-scenario.v1",
        "scenes": [
            {"scene_id": "opening", "intent": "Introduce a quiet world.", "visual_motif": "soft light", "music_motif": "single piano motif"},
            {"scene_id": "turn", "intent": "The player discovers a change.", "visual_motif": "expanding shapes", "music_motif": "rising arpeggio"},
            {"scene_id": "ending", "intent": "Resolve the discovery.", "visual_motif": "warm horizon", "music_motif": "resolved harmony"},
        ],
    }


def _decision():
    return {
        "schema_version": "audiovisual-human-creative-decision.v1",
        "action": "select_candidate", "candidate_id": "candidate-a",
        "human_confirmed_listening": True, "human_confirmed_viewing": True,
        "execution_policy": {"publication_authorized": False},
    }


def test_maps_story_scenes_into_gameplay_and_preserves_motifs():
    result = build_story_driven_godot_design(_scenario(), _decision(), core_interaction="Interact with objects to reveal the story.")
    assert [x["gameplay_role"] for x in result["scene_mapping"]] == ["introduce", "develop", "resolve"]
    assert result["scene_mapping"][1]["player_feedback"]["audio"] == "rising arpeggio"
    assert result["safety_policy"]["project_files_created"] is False


def test_requires_explicit_human_selected_candidate():
    decision = _decision()
    decision["action"] = "reject_all"
    with pytest.raises(ValueError, match="selected human-approved"):
        build_story_driven_godot_design(_scenario(), decision, core_interaction="Explore")


def test_requires_listening_and_viewing_confirmation():
    decision = _decision()
    decision["human_confirmed_listening"] = False
    with pytest.raises(ValueError, match="listening and viewing"):
        build_story_driven_godot_design(_scenario(), decision, core_interaction="Explore")


def test_rejects_duplicate_scene_ids():
    scenario = _scenario()
    scenario["scenes"][1]["scene_id"] = "opening"
    with pytest.raises(ValueError, match="unique"):
        build_story_driven_godot_design(scenario, _decision(), core_interaction="Explore")


def test_rejects_unknown_platform_and_empty_interaction():
    with pytest.raises(ValueError, match="target_platform"):
        build_story_driven_godot_design(_scenario(), _decision(), core_interaction="Explore", target_platform="mobile")
    with pytest.raises(ValueError, match="core_interaction"):
        build_story_driven_godot_design(_scenario(), _decision(), core_interaction=" ")
