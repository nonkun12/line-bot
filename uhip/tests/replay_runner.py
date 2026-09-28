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
    confidence = event.get("confidence", {}).get("calibrated", 1.0)

    if confidence < 0.80:
        return ReplayResult(event_id, False, "low_confidence")
    if event.get("hand_count", 1) != 1:
        return ReplayResult(event_id, False, "multiple_hands")
    if event.get("person_count", 1) != 1:
        return ReplayResult(event_id, False, "multiple_people")
    if event.get("out_of_frame", False):
        return ReplayResult(event_id, False, "out_of_frame")
    if event.get("ttl_ms", 500) <= 0:
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

        if last_seq is not None and (not isinstance(seq, int) or seq <= last_seq):
            results.append(ReplayResult(event_id, False, "sequence_regression"))
            continue

        seen_ids.add(event_id)
        last_seq = seq if isinstance(seq, int) else last_seq
        results.append(evaluate_event(event))

    return results
