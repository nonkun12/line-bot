from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .recognizer import Observation, RecognitionResult, recognize


@dataclass(frozen=True)
class CameraFrame:
    """Minimal frame envelope passed into the local landmark/classifier boundary."""

    frame_id: int
    captured_mono_ns: int
    width: int
    height: int
    data: object


@dataclass(frozen=True)
class ClassifiedHand:
    """Classifier output used to build an Observation.

    The classifier is intentionally outside the Recognition Gate.
    """

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


class CameraSource(Protocol):
    def frames(self) -> Iterable[CameraFrame]:
        """Yield frames locally. Implementations must not perform network I/O."""


class HandClassifier(Protocol):
    def classify(self, frame: CameraFrame) -> ClassifiedHand:
        """Return local classification only; no action authorization is implied."""


@dataclass(frozen=True)
class CameraAdapter:
    """Converts camera frames into gated UHIP results.

    No result is actionable by itself. Every classifier result must pass the
    existing Recognition Gate before a Universal Event draft is produced.
    """

    source: CameraSource
    classifier: HandClassifier
    device_id: str
    session_id: str
    engine: str
    engine_version: str
    model_sha256: str

    def run(self) -> Iterable[RecognitionResult]:
        for seq, frame in enumerate(self.source.frames()):
            classified = self.classifier.classify(frame)
            observation = Observation(
                gesture=classified.gesture,
                confidence_raw=classified.confidence_raw,
                confidence_calibrated=classified.confidence_calibrated,
                stable_frames=classified.stable_frames,
                duration_ms=classified.duration_ms,
                hand_count=classified.hand_count,
                in_frame=classified.in_frame,
                hand_label=classified.hand_label,
                track_id=classified.track_id,
                mirrored=classified.mirrored,
                seq=seq,
                t_mono_ns=frame.captured_mono_ns,
                device_id=self.device_id,
                session_id=self.session_id,
                device_kind="mac",
                sensor="camera",
                engine=self.engine,
                engine_version=self.engine_version,
                model_sha256=self.model_sha256,
            )
            yield recognize(observation)


def bounded_frames(
    frames: Iterable[CameraFrame],
    *,
    max_frames: int = 10_000,
) -> Iterable[CameraFrame]:
    """Bound local camera processing so a caller cannot create an unbounded run."""

    if max_frames < 1:
        raise ValueError("max_frames must be >= 1")
    for index, frame in enumerate(frames):
        if index >= max_frames:
            break
        yield frame
