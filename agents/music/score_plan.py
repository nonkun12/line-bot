"""Scenario-aware music cue planning for audiovisual harmony."""
from __future__ import annotations

from typing import Any

from agents.video.scenario import validate_scenario
from agents.music.motif import ENERGY_OCTAVE, MOTIF_INTERVALS


def build_music_plan(
    scenario: dict[str, Any],
    *,
    genre: str = "映像に合わせたオリジナル音楽",
    instrumentation: str = "映像の世界観に合う編成",
) -> dict[str, Any]:
    """Create a timing- and emotion-aware music plan from a validated scenario.

    This produces a composition brief, not rendered audio or copied music.
    """
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))
    if not isinstance(genre, str) or not genre.strip() or len(genre) > 100:
        raise ValueError("genre must be a non-empty string up to 100 characters")
    if not isinstance(instrumentation, str) or not instrumentation.strip() or len(instrumentation) > 200:
        raise ValueError("instrumentation must be a non-empty string up to 200 characters")

    cues = []
    for scene in scenario["scenes"]:
        sync = scene["music_sync"]
        cues.append({
            "scene_id": scene["scene_id"],
            "start_seconds": scene["time_start_seconds"] + sync["cue_in_seconds"],
            "end_seconds": scene["time_start_seconds"] + sync["cue_out_seconds"],
            "emotional_intent": sync["emotional_intent"],
            "energy": sync["energy"],
            "tempo_relation": sync["tempo_relation"],
            "motif": sync["motif"],
            "sync_points": [
                {
                    "at_seconds": scene["time_start_seconds"] + point["at_seconds"],
                    "event": point["event"],
                }
                for point in sync["sync_points"]
            ],
            "mix_priority": sync["mix_priority"],
        })
    return {
        "schema_version": "video-music-plan.v1",
        "status": "draft",
        "source_scenario_title": scenario["title"],
        "duration_seconds": scenario["creative_brief"]["duration_seconds"],
        "genre": genre.strip(),
        "instrumentation": instrumentation.strip(),
        "global_motif": scenario["audiovisual_direction"]["global_music_motif"],
        "motif_design": {
            "intervals_from_root": list(MOTIF_INTERVALS),
            "energy_register_semitones": dict(ENERGY_OCTAVE),
            "variation_policy": "Keep the melodic interval identity across scenes; vary register and dynamics with scene energy.",
        },
        "emotional_arc": scenario["audiovisual_direction"]["emotional_arc"],
        "cues": cues,
        "mixing_rules": scenario["audiovisual_direction"]["mixing_rules"],
        "originality_policy": "新規に作曲し、既存楽曲の旋律・録音を無断で複製しない",
        "rendering_status": "not_generated",
    }


__all__ = ["build_music_plan"]
