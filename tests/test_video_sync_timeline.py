from __future__ import annotations

import copy

import pytest

from agents.video.sync_timeline import build_audiovisual_sync_timeline


def _edl():
    return {
        "schema_version": "audiovisual-edl.v1",
        "duration_seconds": 4,
        "video_track": [
            {"scene_id": "SC01", "start_seconds": 0, "end_seconds": 2},
            {"scene_id": "SC02", "start_seconds": 2, "end_seconds": 4},
        ],
        "audio_track": [
            {
                "scene_id": "SC01", "start_seconds": 0, "end_seconds": 2,
                "sync_points": [
                    {"at_seconds": 0, "event": "opening"},
                    {"at_seconds": 0.5, "event": "first action"},
                    {"at_seconds": 1.25, "event": "pause"},
                ],
            },
            {
                "scene_id": "SC02", "start_seconds": 2, "end_seconds": 4,
                "sync_points": [
                    {"at_seconds": 2, "event": "climax"},
                    {"at_seconds": 3, "event": "resolution"},
                ],
            },
        ],
    }


def test_maps_authored_events_to_nearest_beat_without_moving_them():
    edl = _edl()
    result = build_audiovisual_sync_timeline(edl, bpm=120)

    assert result["event_count"] == 5
    assert result["on_beat_count"] == 4
    pause = next(item for item in result["events"] if item["event"] == "pause")
    assert pause["nearest_beat_seconds"] == 1.0
    assert pause["authored_at_seconds"] == 1.25
    assert pause["alignment"] == "expressive_offset"
    assert pause["timing_preserved"] is True
    assert edl == _edl()


def test_accepts_intentional_off_beat_event_as_editorial_evidence():
    result = build_audiovisual_sync_timeline(_edl(), bpm=120)
    pause = next(item for item in result["events"] if item["event"] == "pause")
    assert pause["offset_from_beat_seconds"] == 0.25
    assert "do not quantize dialogue" in result["policy"][2]


@pytest.mark.parametrize("bpm", [39, 201, True, 120.0])
def test_rejects_invalid_bpm(bpm):
    with pytest.raises(ValueError, match="bpm"):
        build_audiovisual_sync_timeline(_edl(), bpm=bpm)


def test_rejects_mismatched_scene_tracks():
    edl = _edl()
    edl["audio_track"].pop()
    with pytest.raises(ValueError, match="same scene IDs"):
        build_audiovisual_sync_timeline(edl)


def test_rejects_sync_event_outside_scene():
    edl = _edl()
    edl["audio_track"][0]["sync_points"][0]["at_seconds"] = 2.1
    with pytest.raises(ValueError, match="invalid sync point"):
        build_audiovisual_sync_timeline(edl)


def test_rejects_duplicate_scene_ids():
    edl = _edl()
    edl["video_track"][1]["scene_id"] = "SC01"
    with pytest.raises(ValueError, match="unique"):
        build_audiovisual_sync_timeline(edl)
