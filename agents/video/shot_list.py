"""Shot-list draft generation from a validated storyboard."""
from __future__ import annotations

from typing import Any


def build_shot_list(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Expand storyboard panels into bounded, editable camera shot instructions."""
    if not isinstance(storyboard, dict) or storyboard.get("schema_version") != "video-storyboard.v1":
        raise ValueError("storyboard must use video-storyboard.v1")
    panels = storyboard.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("storyboard panels are required")
    shots = []
    expected_start = 0
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("storyboard panel must be an object")
        required = ("panel_id", "scene_id", "time_start_seconds", "duration_seconds",
                    "frame_description", "shot_size", "camera_motion", "focal_subject",
                    "lighting", "color_palette", "action")
        if any(panel.get(key) is None or panel.get(key) == "" for key in required):
            raise ValueError("storyboard panel is incomplete")
        start = panel["time_start_seconds"]
        duration = panel["duration_seconds"]
        if type(start) is not int or start != expected_start:
            raise ValueError("storyboard panel start times must form a contiguous timeline")
        if type(duration) is not int or duration <= 0:
            raise ValueError("shot duration must be a positive integer")
        if any(not isinstance(panel[key], str) for key in
               ("panel_id", "scene_id", "frame_description", "shot_size",
                "camera_motion", "focal_subject", "lighting", "color_palette", "action")):
            raise ValueError("storyboard panel text fields must be strings")
        expected_start = start + duration
        # A panel is a shot-design unit, not a demand for a single unbroken take.
        # Split longer panels into establishing, action, and resolve coverage.
        cuts = [(0, duration, "主となる画面を成立させる")]
        if duration >= 12:
            first = max(3, duration // 3)
            second = max(first + 1, (duration * 2) // 3)
            cuts = [
                (0, first, "場所・状況を伝える導入カット"),
                (first, second, "主要動作または表情を捉えるカット"),
                (second, duration, "変化と次シーンへの接続を捉えるカット"),
            ]
        for index, (offset, end, purpose) in enumerate(cuts, start=1):
            shots.append({
                "shot_id": f"{panel['scene_id']}-SH{index:02d}",
                "panel_id": panel["panel_id"],
                "scene_id": panel["scene_id"],
                "start_seconds": start + offset,
                "end_seconds": start + end,
                "duration_seconds": end - offset,
                "purpose": purpose,
                "shot_size": panel["shot_size"],
                "camera_motion": panel["camera_motion"],
                "focal_subject": panel["focal_subject"],
                "lighting": panel["lighting"],
                "color_palette": panel["color_palette"],
                "action": panel["action"],
                "transition_out": panel["transition"] if end == duration else "同一シーン内で自然につなぐ",
                "asset_status": "needs_rights_cleared_asset",
            })
    if expected_start != storyboard.get("duration_seconds"):
        raise ValueError("storyboard panels must cover the declared duration")
    return {
        "schema_version": "video-shot-list.v1",
        "status": "draft",
        "source_storyboard": storyboard["source_scenario_title"],
        "duration_seconds": storyboard["duration_seconds"],
        "shots": shots,
        "external_assets_downloaded": False,
        "render_status": "not_rendered",
    }


__all__ = ["build_shot_list"]
