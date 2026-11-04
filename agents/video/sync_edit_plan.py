"""Frame-accurate editorial suggestions derived from authored audiovisual sync points.

The plan is advisory only: it never changes scene boundaries or forces cuts.
"""
from __future__ import annotations

from typing import Any


def build_sync_aware_edit_plan(
    edl: dict[str, Any],
    *,
    fps: int = 30,
) -> dict[str, Any]:
    """Convert authored sync anchors to frame positions and safe edit suggestions."""
    if not isinstance(edl, dict) or edl.get("schema_version") != "audiovisual-edl.v1":
        raise ValueError("edl must use audiovisual-edl.v1")
    if type(fps) is not int or not 1 <= fps <= 60:
        raise ValueError("fps must be an integer from 1 to 60")
    duration = edl.get("duration_seconds")
    scenes = edl.get("video_track")
    if type(duration) not in (int, float) or duration <= 0:
        raise ValueError("EDL duration_seconds must be positive")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("EDL video_track must be a non-empty list")

    alignment_by_event: dict[tuple[str, str, float], str] = {}
    beat_sync = edl.get("beat_sync")
    if beat_sync is not None:
        if not isinstance(beat_sync, dict) or not isinstance(beat_sync.get("events"), list):
            raise ValueError("beat_sync must contain an events list")
        for item in beat_sync["events"]:
            if not isinstance(item, dict):
                raise ValueError("beat_sync events must be objects")
            scene_id = item.get("scene_id")
            event = item.get("event")
            authored_at = item.get("authored_at_seconds")
            alignment = item.get("alignment")
            if (
                not isinstance(scene_id, str) or not isinstance(event, str)
                or type(authored_at) not in (int, float)
                or alignment not in {"on_beat", "expressive_offset"}
            ):
                raise ValueError("beat_sync event fields are invalid")
            alignment_by_event[(scene_id, event, float(authored_at))] = alignment

    suggestions = []
    seen_scene_ids = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("video_track entries must be objects")
        scene_id = scene.get("scene_id")
        start = scene.get("start_seconds")
        end = scene.get("end_seconds")
        if (
            not isinstance(scene_id, str) or not scene_id or scene_id in seen_scene_ids
            or type(start) not in (int, float) or type(end) not in (int, float)
            or start < 0 or end <= start or end > duration
        ):
            raise ValueError("video scene identity or timing is invalid")
        seen_scene_ids.add(scene_id)
        points = scene.get("visual_sync_points", [])
        if not isinstance(points, list):
            raise ValueError("visual_sync_points must be a list")
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("visual sync points must be objects")
            authored_at = point.get("at_seconds")
            event = point.get("event")
            if (
                type(authored_at) not in (int, float)
                or authored_at < start or authored_at > end
                or not isinstance(event, str) or not event.strip()
            ):
                raise ValueError(f"visual sync point is invalid for {scene_id}")
            authored_at = float(authored_at)
            frame_index = round(authored_at * fps)
            frame_time = frame_index / fps
            alignment = alignment_by_event.get((scene_id, event, authored_at), "unanalysed")
            if alignment == "on_beat":
                action = "consider_cut_or_visual_emphasis"
            elif alignment == "expressive_offset":
                action = "preserve_expressive_timing"
            else:
                action = "editor_review_required"
            suggestions.append({
                "scene_id": scene_id,
                "event": event.strip(),
                "authored_at_seconds": authored_at,
                "frame_index": frame_index,
                "frame_time_seconds": round(frame_time, 6),
                "frame_rounding_offset_seconds": round(frame_time - authored_at, 6),
                "beat_alignment": alignment,
                "recommended_action": action,
                "automatic_cut": False,
                "timing_preserved": True,
            })

    suggestions.sort(key=lambda item: (item["authored_at_seconds"], item["scene_id"]))
    return {
        "schema_version": "audiovisual-sync-edit-plan.v1",
        "status": "editorial_suggestions",
        "fps": fps,
        "event_count": len(suggestions),
        "suggestions": suggestions,
        "policy": [
            "map authored events to the nearest output frame for editor reference",
            "never move authored scene or event timestamps",
            "consider cuts or visual emphasis at on-beat events",
            "preserve expressive off-beat timing without forced cuts",
            "never apply an automatic cut from this advisory plan",
        ],
    }


__all__ = ["build_sync_aware_edit_plan"]
