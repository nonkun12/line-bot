"""Deterministic performance-safety checks for handbell arrangements.

This module deliberately validates a declared score/inventory contract; it does
not claim to generate notation or audio. Rendering and score export are separate
typed Goal jobs so a successful validator cannot masquerade as a finished work.
"""
from __future__ import annotations

from math import isfinite
from typing import Any


def validate_handbell_arrangement(arrangement: dict[str, Any]) -> dict[str, Any]:
    """Validate inventory, event references, timing, and basic ringer capacity.

    Expected shape:
      {
        "tempo_bpm": 96,
        "beats_per_measure": 4,
        "performers": [{"id": "P1"}],
        "bells": [{"id": "C5", "pitch": "C5"}],
        "events": [{
          "start_beat": 0, "duration_beats": 1, "pitch": "C5",
          "bell_id": "C5", "performer_id": "P1"
        }]
      }

    A performer may ring at most two bells at once (one per hand). A physical
    bell cannot be assigned overlapping events. More advanced handbell
    techniques and damping rules require additional score annotations.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def error(code: str, index: int | None = None, detail: str = "") -> None:
        item: dict[str, Any] = {"code": code}
        if index is not None:
            item["event_index"] = index
        if detail:
            item["detail"] = detail
        errors.append(item)

    if not isinstance(arrangement, dict):
        return {"valid": False, "errors": [{"code": "arrangement_must_be_object"}], "warnings": []}

    tempo = arrangement.get("tempo_bpm")
    if isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or not isfinite(tempo) or not 20 <= tempo <= 240:
        error("tempo_bpm_out_of_range")

    beats_per_measure = arrangement.get("beats_per_measure")
    if type(beats_per_measure) is not int or not 1 <= beats_per_measure <= 16:
        error("beats_per_measure_invalid")

    performers = arrangement.get("performers")
    bells = arrangement.get("bells")
    events = arrangement.get("events")
    if not isinstance(performers, list) or not performers:
        error("performers_required")
        performers = []
    if not isinstance(bells, list) or not bells:
        error("bell_inventory_required")
        bells = []
    if not isinstance(events, list) or not events:
        error("events_required")
        events = []

    performer_ids: set[str] = set()
    for performer in performers:
        if not isinstance(performer, dict) or not isinstance(performer.get("id"), str) or not performer["id"].strip():
            error("performer_id_invalid")
            continue
        if performer["id"] in performer_ids:
            error("performer_id_duplicate", detail=performer["id"])
        performer_ids.add(performer["id"])

    bell_map: dict[str, str] = {}
    for bell in bells:
        if (
            not isinstance(bell, dict)
            or not isinstance(bell.get("id"), str)
            or not bell["id"].strip()
            or not isinstance(bell.get("pitch"), str)
            or not bell["pitch"].strip()
        ):
            error("bell_inventory_entry_invalid")
            continue
        bell_id = bell["id"]
        if bell_id in bell_map:
            error("bell_id_duplicate", detail=bell_id)
        bell_map[bell_id] = bell["pitch"]

    normalized: list[tuple[float, float, str, str, int]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            error("event_must_be_object", index)
            continue
        start = event.get("start_beat")
        duration = event.get("duration_beats")
        if (
            isinstance(start, bool) or not isinstance(start, (int, float))
            or not isfinite(start) or start < 0
        ):
            error("event_start_invalid", index)
            continue
        if (
            isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not isfinite(duration) or duration <= 0
        ):
            error("event_duration_invalid", index)
            continue
        performer_id = event.get("performer_id")
        bell_id = event.get("bell_id")
        pitch = event.get("pitch")
        if performer_id not in performer_ids:
            error("event_performer_unknown", index)
            continue
        if bell_id not in bell_map:
            error("event_bell_unknown", index)
            continue
        if pitch != bell_map[bell_id]:
            error("event_pitch_does_not_match_bell", index)
            continue
        normalized.append((float(start), float(start + duration), performer_id, bell_id, index))

    # Check overlap using half-open intervals: an event ending at beat N does
    # not overlap another event starting at beat N.
    for i, left in enumerate(normalized):
        start_a, end_a, performer_a, bell_a, index_a = left
        for start_b, end_b, performer_b, bell_b, index_b in normalized[i + 1:]:
            overlaps = start_a < end_b and start_b < end_a
            if not overlaps:
                continue
            if bell_a == bell_b:
                error("physical_bell_overlap", index_b, f"conflicts with event {index_a}")
            if performer_a == performer_b:
                simultaneous = sum(
                    1 for start_c, end_c, performer_c, _, _ in normalized
                    if performer_c == performer_a and start_c < min(end_a, end_b) and max(start_a, start_b) < end_c
                )
                if simultaneous > 2:
                    error("performer_exceeds_two_hands", index_b, f"overlaps event {index_a}")

    # Remove duplicate diagnostics while preserving order.
    unique_errors: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in errors:
        key = (item.get("code"), item.get("event_index"), item.get("detail"))
        if key not in seen:
            seen.add(key)
            unique_errors.append(item)

    if not errors and len(performers) == 1:
        warnings.append({"code": "single_performer_arrangement", "detail": "Confirm the declared performer can manage all part changes."})

    return {
        "valid": not unique_errors,
        "errors": unique_errors,
        "warnings": warnings,
        "event_count": len(events),
        "performer_count": len(performer_ids),
        "bell_count": len(bell_map),
        "validation_scope": [
            "inventory_references",
            "pitch_to_bell_mapping",
            "event_timing",
            "physical_bell_overlap",
            "two_hand_capacity",
        ],
        "not_yet_validated": [
            "notation_readability",
            "ringing_and_damping_techniques",
            "page_turns",
            "musicality",
            "score_to_audio_consistency",
        ],
    }
