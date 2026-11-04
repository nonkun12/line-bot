"""Translate an approved audiovisual story into a traceable Godot game design.

Design artifact only: no project generation, execution, asset changes, or publication.
"""
from __future__ import annotations

import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def build_story_driven_godot_design(
    scenario: dict[str, Any],
    decision: dict[str, Any],
    *,
    core_interaction: str,
    target_platform: str = "desktop",
) -> dict[str, Any]:
    if not isinstance(scenario, dict) or scenario.get("schema_version") != "video-scenario.v1":
        raise ValueError("scenario must use video-scenario.v1")
    if not isinstance(decision, dict) or decision.get("schema_version") != "audiovisual-human-creative-decision.v1":
        raise ValueError("a valid human creative decision is required")
    if decision.get("action") != "select_candidate" or not decision.get("candidate_id"):
        raise ValueError("a selected human-approved candidate is required")
    policy = decision.get("execution_policy")
    if not isinstance(policy, dict) or policy.get("publication_authorized") is not False:
        raise ValueError("decision execution policy is invalid")
    if decision.get("human_confirmed_listening") is not True or decision.get("human_confirmed_viewing") is not True:
        raise ValueError("human listening and viewing confirmation are required")
    if not isinstance(core_interaction, str) or not core_interaction.strip() or len(core_interaction) > 500:
        raise ValueError("core_interaction must contain 1..500 characters")
    if not isinstance(target_platform, str) or target_platform not in {"desktop", "web"}:
        raise ValueError("target_platform must be desktop or web")

    scenes = scenario.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("scenario must contain scenes")
    normalized = []
    seen = set()
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError("each scene must be an object")
        scene_id = scene.get("scene_id", scene.get("id"))
        if not isinstance(scene_id, str) or not _ID.fullmatch(scene_id) or scene_id in seen:
            raise ValueError("scene IDs must be valid and unique")
        seen.add(scene_id)
        intent = scene.get("intent", scene.get("description"))
        if not isinstance(intent, str) or not intent.strip():
            raise ValueError(f"scene {scene_id} requires an intent")
        visual = scene.get("visual_motif", scene.get("visual_direction", ""))
        music = scene.get("music_motif", scene.get("music_direction", ""))
        if not isinstance(visual, str) or not isinstance(music, str):
            raise ValueError(f"scene {scene_id} motif descriptions must be strings")
        normalized.append({
            "scene_id": scene_id, "sequence": index, "story_intent": intent.strip(),
            "visual_motif": visual.strip(), "music_motif": music.strip(),
            "gameplay_role": "introduce" if index == 1 else "develop" if index < len(scenes) else "resolve",
            "player_feedback": {
                "visual": visual.strip() or "Reflect the current scene state without adding unapproved story facts.",
                "audio": music.strip() or "Use the approved scene music motif; preserve authored timing.",
            },
        })
    return {
        "schema_version": "godot-game-design.v1",
        "source_scenario_schema": scenario["schema_version"],
        "approved_candidate_id": decision["candidate_id"],
        "target_platform": target_platform,
        "engine": "Godot",
        "creative_direction": {
            "core_interaction": core_interaction.strip(),
            "design_rule": "Player actions must express or reveal the approved story intent.",
            "audio_visual_rule": "Music and visual motifs provide coordinated, readable player feedback.",
        },
        "scene_mapping": normalized,
        "prototype_scope": {
            "first_playable_loop": [
                "enter the opening scene", "perform the core interaction",
                "receive synchronized visual and musical feedback",
                "advance the story state", "reach a short resolution",
            ],
            "defer_until_later_sprint": [
                "large open worlds", "online multiplayer", "paid assets or services",
                "unapproved narrative branches",
            ],
        },
        "suggested_godot_structure": {
            "main_scene": "res://scenes/main.tscn",
            "story_controller": "res://scripts/story_controller.gd",
            "audio_controller": "res://scripts/audio_controller.gd",
            "visual_controller": "res://scripts/visual_controller.gd",
            "scene_resources": "res://scenes/story/",
            "test_directory": "res://tests/",
        },
        "interaction_spec": {
            "input_actions": ["interact", "confirm", "pause"],
            "state_changes_must_be_deterministic": True,
            "scene_transition_requires_valid_story_state": True,
            "audio_visual_events_share_scene_id": True,
            "no_external_network_dependency": True,
        },
        "acceptance_checks": [
            "project opens in the selected Godot target",
            "the first playable loop can be completed",
            "each scene transition preserves story order",
            "music and visual feedback reference the same scene ID",
            "all referenced media assets have an approval record",
            "automated tests pass and a human playtest is recorded",
        ],
        "safety_policy": {
            "design_only": True, "project_files_created": False,
            "media_assets_modified": False, "automatic_publication": False,
            "human_playtest_required": True,
        },
    }


__all__ = ["build_story_driven_godot_design"]
