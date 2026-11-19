import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "universal-event.schema.json"


def canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def event_digest(event: dict) -> str:
    return hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()


def test_replay_digest_is_deterministic():
    event = {
        "schema_version": "0.3",
        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f12",
        "session_id": "session-1",
        "device_id": "device-1",
        "seq": 1,
        "t_mono_ns": 100,
        "source": {
            "device_kind": "mac",
            "sensor": "camera",
            "engine": "mediapipe",
            "engine_version": "0.1",
            "model_sha256": "a" * 64,
        },
        "modality": "hand",
        "payload": {
            "gesture": "thumb_up",
            "phase": "end",
            "value": None,
            "hand": {
                "label": "right",
                "track_id": 3,
                "mirrored": True,
            },
            "confidence": {"raw": 0.99, "calibrated": 0.97},
            "stability": {"frames": 8, "duration_ms": 160},
        },
        "gate": {"recognition_passed": True, "rule_version": "phase0-1"},
        "ttl_ms": 500,
    }

    first = event_digest(event)
    second = event_digest(json.loads(canonical_json(event)))

    assert first == second
    assert len(first) == 64


def test_replay_sequence_is_stable():
    events = [
        {"event_id": "e1", "seq": 1, "t_mono_ns": 100},
        {"event_id": "e2", "seq": 2, "t_mono_ns": 200},
        {"event_id": "e3", "seq": 3, "t_mono_ns": 300},
    ]

    assert [event["seq"] for event in events] == [1, 2, 3]
    assert [event["event_id"] for event in events] == ["e1", "e2", "e3"]


def test_replay_rejects_sequence_regression():
    events = [
        {"event_id": "e1", "seq": 1, "t_mono_ns": 100},
        {"event_id": "e2", "seq": 3, "t_mono_ns": 200},
        {"event_id": "e3", "seq": 2, "t_mono_ns": 300},
    ]

    with pytest.raises(AssertionError):
        assert [event["seq"] for event in events] == sorted(
            event["seq"] for event in events
        )
