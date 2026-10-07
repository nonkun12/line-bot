from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5


Gesture = Literal[
    "thumb_up",
    "swipe_left",
    "swipe_right",
    "open_palm",
    "fist",
    "pinch",
]

_ALLOWED_GESTURES = frozenset(
    {"thumb_up", "swipe_left", "swipe_right", "open_palm", "fist", "pinch"}
)


@dataclass(frozen=True)
class GatePolicy:
    """Fail-closed Recognition Gate policy for Phase 0."""

    min_confidence: float = 0.90
    min_stable_frames: int = 3
    max_hands: int = 1
    ttl_ms: int = 500

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.min_stable_frames < 1:
            raise ValueError("min_stable_frames must be >= 1")
        if self.max_hands != 1:
            raise ValueError("Phase 0 requires max_hands=1")
        if self.ttl_ms < 1:
            raise ValueError("ttl_ms must be >= 1")


@dataclass(frozen=True)
class Observation:
    """Local recognition output before it becomes a Universal Event."""

    gesture: str
    confidence_raw: float
    confidence_calibrated: float
    stable_frames: int
    duration_ms: int
    hand_count: int
    in_frame: bool
    hand_label: str
    track_id: int
    mirrored: bool
    seq: int
    t_mono_ns: int
    device_id: str
    session_id: str
    device_kind: str = "mac"
    sensor: str = "camera"
    engine: str = "local-rule"
    engine_version: str = "0.1"
    model_sha256: str = "phase0-no-model"

    def __post_init__(self) -> None:
        if self.gesture not in _ALLOWED_GESTURES:
            raise ValueError(f"unsupported gesture: {self.gesture}")
        if not 0.0 <= self.confidence_raw <= 1.0:
            raise ValueError("confidence_raw must be between 0 and 1")
        if not 0.0 <= self.confidence_calibrated <= 1.0:
            raise ValueError("confidence_calibrated must be between 0 and 1")
        if self.stable_frames < 0 or self.duration_ms < 0:
            raise ValueError("stability values must be >= 0")
        if self.hand_count < 0:
            raise ValueError("hand_count must be >= 0")
        if self.track_id < 0 or self.seq < 0 or self.t_mono_ns < 0:
            raise ValueError("sequence and tracking values must be >= 0")
        if not self.device_id or not self.session_id:
            raise ValueError("device_id and session_id are required")
        if not self.model_sha256:
            raise ValueError("model_sha256 is required")


@dataclass(frozen=True)
class RecognitionResult:
    passed: bool
    reason: str
    event: dict[str, Any] | None = None


def recognize(
    observation: Observation,
    policy: GatePolicy | None = None,
) -> RecognitionResult:
    """Apply the Phase 0 Recognition Gate and build a non-actionable event draft.

    Any gate failure returns no event. This function performs no network or OS action.
    """

    active_policy = policy or GatePolicy()

    if observation.hand_count != active_policy.max_hands:
        return RecognitionResult(False, "hand_count")
    if not observation.in_frame:
        return RecognitionResult(False, "out_of_frame")
    if observation.confidence_raw < active_policy.min_confidence:
        return RecognitionResult(False, "raw_confidence")
    if observation.confidence_calibrated < active_policy.min_confidence:
        return RecognitionResult(False, "calibrated_confidence")
    if observation.stable_frames < active_policy.min_stable_frames:
        return RecognitionResult(False, "unstable")
    if observation.gesture not in _ALLOWED_GESTURES:
        return RecognitionResult(False, "gesture_not_allowlisted")
    if observation.hand_label not in {"left", "right", "unknown"}:
        return RecognitionResult(False, "hand_label")
    if observation.device_kind != "mac" or observation.sensor != "camera":
        return RecognitionResult(False, "phase0_source")
    
    event = {
        "schema_version": "0.3",
        "event_id": str(uuid5(NAMESPACE_URL, f"uhip:{observation.session_id}:{observation.seq}:{observation.t_mono_ns}")),
        "session_id": observation.session_id,
        "device_id": observation.device_id,
        "seq": observation.seq,
        "t_mono_ns": observation.t_mono_ns,
        "source": {
            "device_kind": observation.device_kind,
            "sensor": observation.sensor,
            "engine": observation.engine,
            "engine_version": observation.engine_version,
            "model_sha256": observation.model_sha256,
        },
        "modality": "hand",
        "payload": {
            "gesture": observation.gesture,
            "phase": "end",
            "value": None,
            "hand": {
                "label": observation.hand_label,
                "track_id": observation.track_id,
                "mirrored": observation.mirrored,
            },
            "confidence": {
                "raw": observation.confidence_raw,
                "calibrated": observation.confidence_calibrated,
            },
            "stability": {
                "frames": observation.stable_frames,
                "duration_ms": observation.duration_ms,
            },
            "local": True,
        },
        "gate": {
            "recognition_passed": True,
            "rule_version": "phase0-1",
        },
        "ttl_ms": active_policy.ttl_ms,
    }
    return RecognitionResult(True, "accepted", event)
