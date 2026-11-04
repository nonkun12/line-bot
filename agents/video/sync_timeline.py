"""Beat-aware editorial timing analysis for audiovisual production drafts.

This annotates authored visual events against the composition's beat grid.
It never moves story events or scene boundaries: musical alignment is evidence
for an editor/critic, not an automatic rewrite of creative intent.
"""
from __future__ import annotations

from typing import Any

MIN_BPM = 40
MAX_BPM = 200
DEFAULT_ON_BEAT_TOLERANCE_SECONDS = 0.08


def build_audiovisual_sync_timeline(
    edl: dict[str, Any],
    *,
    bpm: int = 120,
    on_beat_tolerance_seconds: float = DEFAULT_ON_BEAT_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Map authored sync events to the nearest beat without changing their time."""
    if not isinstance(edl, dict) or edl.get("schema_version") != "audiovisual-edl.v1":
        raise ValueError("edl must use audiovisual-edl.v1")
    if type(bpm) is not int or not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"bpm must be an integer from {MIN_BPM} to {MAX_BPM}")
    if (
        type(on_beat_tolerance_seconds) not in (int, float)
        or not 0 <= on_beat_tolerance_seconds <= 0.25
    ):
        raise ValueError("on_beat_tolerance_seconds must be between 0 and 0.25")
    duration = edl.get("duration_seconds")
    video = edl.get("video_track")
    audio = edl.get("audio_track")
    if type(duration) not in (int, float) or duration <= 0:
        raise ValueError("EDL duration_seconds must be positive")
    if not isinstance(video, list) or not video or not isinstance(audio, list):
        raise ValueError("EDL video_track and audio_track must be non-empty lists")

    video_by_id = {}
    for scene in video:
        if not isinstance(scene, dict):
            raise ValueError("video_track entries must be objects")
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id or scene_id in video_by_id:
            raise ValueError("video scene IDs must be unique non-empty strings")
        start = scene.get("start_seconds")
        end = scene.get("end_seconds")
        if (
            type(start) not in (int, float) or type(end) not in (int, float)
            or start < 0 or end <= start or end > duration
        ):
            raise ValueError(f"invalid video timing for {scene_id}")
        video_by_id[scene_id] = (float(start), float(end))

    beat_seconds = 60.0 / bpm
    scene_results = []
    seen_audio_ids = set()
    all_events = []
    for cue in audio:
        if not isinstance(cue, dict):
            raise ValueError("audio_track entries must be objects")
        scene_id = cue.get("scene_id")
        if scene_id not in video_by_id or scene_id in seen_audio_ids:
            raise ValueError("audio scene IDs must match video scene IDs exactly")
        seen_audio_ids.add(scene_id)
        scene_start, scene_end = video_by_id[scene_id]
        cue_start = cue.get("start_seconds")
        cue_end = cue.get("end_seconds")
        if (
            type(cue_start) not in (int, float) or type(cue_end) not in (int, float)
            or cue_start < scene_start or cue_end > scene_end or cue_end <= cue_start
        ):
            raise ValueError(f"invalid audio cue timing for {scene_id}")
        sync_points = cue.get("sync_points")
        if not isinstance(sync_points, list):
            raise ValueError(f"sync_points must be a list for {scene_id}")
        events = []
        for point in sync_points:
            if not isinstance(point, dict):
                raise ValueError("sync points must be objects")
            at = point.get("at_seconds")
            event = point.get("event")
            if (
                type(at) not in (int, float) or at < scene_start or at > scene_end
                or not isinstance(event, str) or not event.strip()
            ):
                raise ValueError(f"invalid sync point for {scene_id}")
            beat_index = round(float(at) / beat_seconds)
            nearest_beat = beat_index * beat_seconds
            offset = float(at) - nearest_beat
            item = {
                "scene_id": scene_id,
                "event": event,
                "authored_at_seconds": float(at),
                "nearest_beat_index": beat_index,
                "nearest_beat_seconds": round(nearest_beat, 6),
                "offset_from_beat_seconds": round(offset, 6),
                "alignment": (
                    "on_beat"
                    if abs(offset) <= on_beat_tolerance_seconds
                    else "expressive_offset"
                ),
                "timing_preserved": True,
            }
            events.append(item)
            all_events.append(item)
        scene_results.append({
            "scene_id": scene_id,
            "scene_start_seconds": scene_start,
            "scene_end_seconds": scene_end,
            "events": events,
        })

    if seen_audio_ids != set(video_by_id):
        raise ValueError("audio and video tracks must contain the same scene IDs")
    all_events.sort(key=lambda item: (item["authored_at_seconds"], item["scene_id"]))
    on_beat_count = sum(item["alignment"] == "on_beat" for item in all_events)
    total = len(all_events)
    return {
        "schema_version": "audiovisual-sync-timeline.v1",
        "status": "analysis",
        "bpm": bpm,
        "beat_seconds": round(beat_seconds, 6),
        "on_beat_tolerance_seconds": on_beat_tolerance_seconds,
        "event_count": total,
        "on_beat_count": on_beat_count,
        "on_beat_ratio": round(on_beat_count / total, 4) if total else None,
        "scenes": scene_results,
        "events": all_events,
        "policy": [
            "preserve authored scene and event timestamps",
            "report nearest-beat alignment as editorial evidence",
            "do not quantize dialogue, action, or emotional pauses automatically",
            "allow intentional off-beat timing when it serves the story",
        ],
    }


__all__ = ["build_audiovisual_sync_timeline"]
