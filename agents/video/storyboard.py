"""Deterministic storyboard draft generation from an approved scenario."""
from __future__ import annotations

from typing import Any

from agents.video.scenario import validate_scenario


def build_storyboard(scenario: dict[str, Any]) -> dict[str, Any]:
    """Create one editable storyboard panel per scenario scene."""
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))
    panels = []
    for scene in scenario["scenes"]:
        shot = scene["shot_plan"]
        panels.append({
            "panel_id": f"SB-{scene['scene_id']}",
            "scene_id": scene["scene_id"],
            "time_start_seconds": scene["time_start_seconds"],
            "duration_seconds": scene["duration_seconds"],
            "frame_description": scene["visual_direction"],
            "composition": shot["composition_note"],
            "shot_size": shot["shot_size"],
            "camera_motion": shot["camera_motion"],
            "focal_subject": shot["focal_subject"],
            "lighting": shot["lighting"],
            "color_palette": shot["color_palette"],
            "action": scene["action"],
            "dialogue_or_narration": scene["dialogue_or_narration"],
            "audio_cue": scene["audio_direction"],
            "music_energy": scene["music_sync"]["energy"],
            "transition": scene["transition"],
            "asset_status": "not_created",
        })
    return {
        "schema_version": "video-storyboard.v1",
        "status": "draft",
        "source_scenario_title": scenario["title"],
        "duration_seconds": scenario["creative_brief"]["duration_seconds"],
        "panels": panels,
        "review_required": [
            "人物・場所・小道具の連続性",
            "各パネルの画面意図とナレーションの一致",
            "音楽の盛り上がりと画面変化の同期",
            "権利処理済み素材のみを使用すること",
        ],
        "render_status": "not_rendered",
    }


__all__ = ["build_storyboard"]
