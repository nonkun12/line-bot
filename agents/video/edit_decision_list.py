"""Scenario- and score-aware edit decision list (EDL) generation."""
from __future__ import annotations

from typing import Any

from agents.video.scenario import validate_scenario
from agents.video.sync_timeline import build_audiovisual_sync_timeline


def build_edit_decision_list(
    scenario: dict[str, Any],
    music_plan: dict[str, Any],
    *,
    bpm: int = 120,
) -> dict[str, Any]:
    """Create an editable, synchronized video/audio timeline manifest.

    This is a render-ready plan, not a rendered video file. It contains no
    external assets and never downloads or publishes media.
    """
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))
    if not isinstance(music_plan, dict) or music_plan.get("schema_version") != "video-music-plan.v1":
        raise ValueError("music_plan must use video-music-plan.v1")
    duration = scenario["creative_brief"]["duration_seconds"]
    if music_plan.get("duration_seconds") != duration:
        raise ValueError("scenario and music plan durations must match")
    cues = music_plan.get("cues")
    if not isinstance(cues, list):
        raise ValueError("music cues must be a list")
    cues_by_scene = {}
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("music cue must be an object")
        scene_id = cue.get("scene_id")
        if not isinstance(scene_id, str) or scene_id in cues_by_scene:
            raise ValueError("music cue scene_id is invalid or duplicated")
        cues_by_scene[scene_id] = cue

    video_track = []
    audio_track = []
    expected_start = 0
    for scene in scenario["scenes"]:
        scene_id = scene["scene_id"]
        start = scene["time_start_seconds"]
        end = start + scene["duration_seconds"]
        if start != expected_start:
            raise ValueError("scenario scenes must form a contiguous timeline")
        expected_start = end
        cue = cues_by_scene.get(scene_id)
        if cue is None:
            raise ValueError(f"music cue missing for scene {scene_id}")
        cue_start = cue.get("start_seconds")
        cue_end = cue.get("end_seconds")
        if (
            type(cue_start) not in (int, float)
            or type(cue_end) not in (int, float)
            or cue_start < start or cue_end > end or cue_end <= cue_start
        ):
            raise ValueError(f"music cue for {scene_id} falls outside its scene")
        sync_points = cue.get("sync_points")
        if not isinstance(sync_points, list) or not sync_points:
            raise ValueError(f"music cue for {scene_id} must contain sync points")
        normalized_sync_points = []
        for point in sync_points:
            if not isinstance(point, dict):
                raise ValueError(f"music sync point for {scene_id} must be an object")
            at_seconds = point.get("at_seconds")
            event = point.get("event")
            if (type(at_seconds) not in (int, float) or at_seconds < cue_start
                    or at_seconds > cue_end or not isinstance(event, str)
                    or not event.strip() or len(event) > 240):
                raise ValueError(f"music sync point for {scene_id} is invalid")
            normalized_sync_points.append({
                "at_seconds": float(at_seconds),
                "scene_offset_seconds": float(at_seconds) - float(start),
                "event": event.strip(),
            })
        normalized_sync_points.sort(key=lambda item: item["at_seconds"])
        video_track.append({
            "scene_id": scene_id,
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": scene["duration_seconds"],
            "visual_direction": scene["visual_direction"],
            "action": scene["action"],
            "shot_size": scene["shot_plan"]["shot_size"],
            "camera_motion": scene["shot_plan"]["camera_motion"],
            "focal_subject": scene["shot_plan"]["focal_subject"],
            "dialogue_or_narration": scene["dialogue_or_narration"],
            "transition": scene["transition"],
            "continuity": scene["continuity"],
            "asset_status": "needs_rights_cleared_asset",
            "visual_sync_points": normalized_sync_points,
        })
        audio_track.append({
            "scene_id": scene_id,
            "start_seconds": cue_start,
            "end_seconds": cue_end,
            "emotional_intent": cue["emotional_intent"],
            "energy": cue["energy"],
            "motif": cue["motif"],
            "sync_points": normalized_sync_points,
            "mix_priority": cue["mix_priority"],
            "render_status": "not_rendered",
        })

    if expected_start != duration:
        raise ValueError("scene timeline does not cover the full scenario duration")
    if set(cues_by_scene) != {scene["scene_id"] for scene in scenario["scenes"]}:
        raise ValueError("music plan contains cues without matching scenes")
    beat_sync = build_audiovisual_sync_timeline({
        "schema_version": "audiovisual-edl.v1",
        "duration_seconds": duration,
        "video_track": video_track,
        "audio_track": audio_track,
    }, bpm=bpm)
    return {
        "schema_version": "audiovisual-edl.v1",
        "status": "draft",
        "title": scenario["title"],
        "duration_seconds": duration,
        "video_track": video_track,
        "audio_track": audio_track,
        "beat_sync": beat_sync,
        "sync_events": sorted(
            [point for scene in video_track for point in scene["visual_sync_points"]],
            key=lambda item: item["at_seconds"],
        ),
        "sync_policy": [
            "preserve scenario scene boundaries",
            "align music cues to scene-level emotional intent",
            "expose authored sync points to the video editor as visual timing anchors",
            "respect authored sync points and mix priorities",
            "use intentional silence when no cue is present",
        ],
        "render_status": "not_rendered",
        "rights_status": "assets_not_attached",
    }


__all__ = ["build_edit_decision_list"]
