from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ReplayResult:
    event_id: str
    accepted: bool
    reason: str


def evaluate_event(event: dict) -> ReplayResult:
    event_id = str(event.get("event_id", ""))
    if not event_id:
        return ReplayResult(event_id, False, "missing_event_id")

    gate = event.get("gate")
    if not isinstance(gate, dict) or gate.get("recognition_passed") is not True:
        return ReplayResult(event_id, False, "recognition_gate_failed")

    confidence = event.get("confidence", {}).get("calibrated") if isinstance(event.get("confidence"), dict) else None
    if not isinstance(confidence, (int, float)) or confidence < 0.80:
        return ReplayResult(event_id, False, "low_confidence")

    hand_count = event.get("hand_count", 1)
    person_count = event.get("person_count", 1)
    if not isinstance(hand_count, int) or hand_count != 1:
        return ReplayResult(event_id, False, "multiple_hands")
    if not isinstance(person_count, int) or person_count != 1:
        return ReplayResult(event_id, False, "multiple_people")
    if event.get("out_of_frame", False):
        return ReplayResult(event_id, False, "out_of_frame")

    ttl_ms = event.get("ttl_ms")
    if not isinstance(ttl_ms, int) or ttl_ms <= 0:
        return ReplayResult(event_id, False, "expired_ttl")

    return ReplayResult(event_id, True, "accepted")


def replay(events: Iterable[dict]) -> list[ReplayResult]:
    results: list[ReplayResult] = []
    seen_ids: set[str] = set()
    last_seq: int | None = None

    for event in events:
        event_id = str(event.get("event_id", ""))
        seq = event.get("seq")

        if event_id in seen_ids:
            results.append(ReplayResult(event_id, False, "duplicate_event_id"))
            continue

        if not isinstance(seq, int) or seq < 0:
            results.append(ReplayResult(event_id, False, "invalid_sequence"))
            continue

        if last_seq is not None and seq <= last_seq:
            results.append(ReplayResult(event_id, False, "sequence_regression"))
            continue

        seen_ids.add(event_id)
        last_seq = seq
        results.append(evaluate_event(event))

    return results
