import json
from pathlib import Path

import pytest

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]
EVENT_SCHEMA = ROOT / "schema" / "universal-event.schema.json"
ADAPTER_SCHEMA = ROOT / "schema" / "application-adapter.schema.json"


pytestmark = pytest.mark.skipif(
    jsonschema is None,
    reason="jsonschema is required for UHIP schema contract tests",
)


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(instance: dict, schema_path: Path) -> None:
    jsonschema.Draft202012Validator(load_schema(schema_path)).validate(instance)


def test_universal_event_accepts_generic_hand_event():
    event = {
        "schema_version": "0.3",
        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f12",
        "session_id": "session-1",
        "device_id": "device-1",
        "seq": 1,
        "t_mono_ns": 100,
        "t_wall": "2026-09-28T01:00:00Z",
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
            "confidence": {
                "raw": 0.99,
                "calibrated": 0.97,
            },
            "stability": {
                "frames": 8,
                "duration_ms": 160,
            },
        },
        "gate": {
            "recognition_passed": True,
            "rule_version": "phase0-1",
        },
        "ttl_ms": 500,
    }
    validate(event, EVENT_SCHEMA)


def test_universal_event_accepts_hand_event_when_recognition_gate_fails():
    event = {
        "schema_version": "0.3",
        "event_id": "0192f0f8-7d4a-7c1b-9d4e-7d9d3c7c9f13",
        "session_id": "session-1",
        "device_id": "device-1",
        "seq": 2,
        "t_mono_ns": 200,
        "t_wall": "2026-09-30T13:00:00Z",
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
            "confidence": {
                "raw": 0.42,
                "calibrated": 0.40,
            },
            "stability": {
                "frames": 2,
                "duration_ms": 40,
            },
        },
        "gate": {
            "recognition_passed": False,
            "rule_version": "phase0-1",
        },
        "ttl_ms": 500,
    }
    validate(event, EVENT_SCHEMA)


def test_universal_event_rejects_application_specific_command():
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
            "gesture": "send_line_message",
            "phase": "end",
            "value": None,
            "hand": {
                "label": "right",
                "track_id": 3,
                "mirrored": True,
            },
            "confidence": {
                "raw": 0.99,
                "calibrated": 0.97,
            },
            "stability": {
                "frames": 8,
                "duration_ms": 160,
            },
        },
        "gate": {
            "recognition_passed": True,
            "rule_version": "phase0-1",
        },
        "ttl_ms": 500,
    }
    with pytest.raises(jsonschema.ValidationError):
        validate(event, EVENT_SCHEMA)


def test_adapter_schema_accepts_generic_browser_capability():
    adapter = {
        "schema_version": "0.1",
        "adapter_id": "browser",
        "version": "0.1",
        "modalities": ["hand"],
        "events": ["thumb_up", "swipe_left"],
        "targets": ["com.apple.Safari"],
        "max_risk": "low",
        "confirmation": "policy",
        "actuator": "separate_process",
        "policy_version": "browser-policy-1",
    }
    validate(adapter, ADAPTER_SCHEMA)


def test_adapter_schema_rejects_unknown_risk():
    adapter = {
        "schema_version": "0.1",
        "adapter_id": "browser",
        "version": "0.1",
        "modalities": ["hand"],
        "events": ["thumb_up"],
        "targets": ["com.apple.Safari"],
        "max_risk": "critical",
        "confirmation": "policy",
        "actuator": "separate_process",
    }
    with pytest.raises(jsonschema.ValidationError):
        validate(adapter, ADAPTER_SCHEMA)
