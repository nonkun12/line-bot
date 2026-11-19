from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .recognizer import GatePolicy, Observation, RecognitionResult, recognize


_MAX_LINE_BYTES = 64 * 1024
_MAX_RECORDS = 10_000


@dataclass(frozen=True)
class ReplayResult:
    index: int
    result: RecognitionResult


def _observation_from_record(record: dict[str, Any]) -> Observation:
    return Observation(
        gesture=str(record["gesture"]),
        confidence_raw=float(record["confidence_raw"]),
        confidence_calibrated=float(record["confidence_calibrated"]),
        stable_frames=int(record["stable_frames"]),
        duration_ms=int(record["duration_ms"]),
        hand_count=int(record["hand_count"]),
        in_frame=bool(record["in_frame"]),
        hand_label=str(record["hand_label"]),
        track_id=int(record["track_id"]),
        mirrored=bool(record["mirrored"]),
        seq=int(record["seq"]),
        t_mono_ns=int(record["t_mono_ns"]),
        device_id=str(record["device_id"]),
        session_id=str(record["session_id"]),
        device_kind=str(record.get("device_kind", "mac")),
        sensor=str(record.get("sensor", "camera")),
        engine=str(record.get("engine", "local-rule")),
        engine_version=str(record.get("engine_version", "0.1")),
        model_sha256=str(record.get("model_sha256", "phase0-no-model")),
    )


def replay_lines(
    lines: Iterable[str],
    policy: GatePolicy | None = None,
) -> list[ReplayResult]:
    """Replay bounded JSONL observations deterministically.

    Invalid records fail closed and do not emit events. No external I/O is performed.
    """

    results: list[ReplayResult] = []
    for index, line in enumerate(lines):
        if index >= _MAX_RECORDS:
            break

        if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
            results.append(
                ReplayResult(index, RecognitionResult(False, "record_too_large"))
            )
            continue

        if not line.strip():
            continue

        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("record_not_object")
            observation = _observation_from_record(record)
            result = recognize(observation, policy)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result = RecognitionResult(False, f"invalid_record:{type(exc).__name__}")
        results.append(ReplayResult(index, result))

    return results
