from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

from .camera_adapter import CameraFrame, ClassifiedHand


def _xy(landmark: object) -> tuple[float, float]:
    return float(landmark.x), float(landmark.y)


def _distance(a: object, b: object) -> float:
    ax, ay = _xy(a)
    bx, by = _xy(b)
    return hypot(ax - bx, ay - by)


def classify_landmarks(landmarks: list[object]) -> tuple[str, float]:
    """Conservative local geometry classifier for the Phase 0 allowlist."""
    if len(landmarks) != 21:
        return "unknown", 0.0

    wrist = landmarks[0]
    fingers = ((8, 6), (12, 10), (16, 14), (20, 18))
    extended = []
    for tip, pip in fingers:
        extended.append(
            _distance(wrist, landmarks[tip])
            > _distance(wrist, landmarks[pip]) * 1.12
        )

    thumb_ratio = _distance(wrist, landmarks[4]) / max(
        _distance(wrist, landmarks[3]), 1e-9
    )
    thumb_extended = thumb_ratio > 1.08
    _, thumb_y = _xy(landmarks[4])
    _, wrist_y = _xy(wrist)
    thumb_up = thumb_extended and thumb_y < wrist_y - 0.03

    if all(extended) and thumb_extended:
        return "open_palm", 0.96
    if thumb_up and not any(extended):
        return "thumb_up", 0.95
    if not any(extended) and not thumb_extended:
        return "fist", 0.94
    return "unknown", 0.0


@dataclass
class MediaPipeHandsClassifier:
    """Local MediaPipe Hands adapter without the MediaPipe Tasks API."""

    min_detection_confidence: float = 0.70
    min_tracking_confidence: float = 0.70
    _hands: object | None = field(default=None, init=False, repr=False)
    _last_key: tuple[str, str] | None = field(default=None, init=False, repr=False)
    _stable_frames: int = field(default=0, init=False, repr=False)
    _stable_since_ns: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_detection_confidence <= 1.0:
            raise ValueError("min_detection_confidence must be between 0 and 1")
        if not 0.0 <= self.min_tracking_confidence <= 1.0:
            raise ValueError("min_tracking_confidence must be between 0 and 1")
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError(
                "MediaPipe is not installed. Install requirements-uhip-mac.txt."
            ) from exc
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )

    def close(self) -> None:
        if self._hands is not None:
            self._hands.close()
            self._hands = None

    def classify(self, frame: CameraFrame) -> ClassifiedHand:
        if self._hands is None:
            raise RuntimeError("MediaPipe Hands classifier is closed")
        if frame.data is None:
            self._reset_stability()
            return self._unknown()

        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV is not installed. Install requirements-uhip-mac.txt."
            ) from exc

        image = frame.data
        if getattr(image, "ndim", 0) != 3 or image.shape[2] != 3:
            self._reset_stability()
            return self._unknown()

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)
        detected = result.multi_hand_landmarks or []
        hand_count = len(detected)

        if hand_count == 0:
            self._reset_stability()
            return self._unknown()

        handedness = "unknown"
        if result.multi_handedness:
            label = result.multi_handedness[0].classification[0].label
            handedness = {"Left": "right", "Right": "left"}.get(label, "unknown")

        gesture, confidence = classify_landmarks(list(detected[0].landmark))

        if hand_count != 1:
            self._reset_stability()
            return ClassifiedHand(
                gesture=gesture,
                confidence_raw=confidence,
                confidence_calibrated=confidence,
                stable_frames=0,
                duration_ms=0,
                hand_count=hand_count,
                in_frame=True,
                hand_label=handedness,
                track_id=0,
                mirrored=False,
            )

        if gesture == "unknown":
            self._reset_stability()
            return ClassifiedHand(
                gesture="unknown",
                confidence_raw=0.0,
                confidence_calibrated=0.0,
                stable_frames=0,
                duration_ms=0,
                hand_count=1,
                in_frame=True,
                hand_label=handedness,
                track_id=1,
                mirrored=False,
            )

        key = (gesture, handedness)
        if key == self._last_key:
            self._stable_frames += 1
        else:
            self._last_key = key
            self._stable_frames = 1
            self._stable_since_ns = frame.captured_mono_ns

        started_ns = self._stable_since_ns or frame.captured_mono_ns
        duration_ms = max(0, (frame.captured_mono_ns - started_ns) // 1_000_000)
        return ClassifiedHand(
            gesture=gesture,
            confidence_raw=confidence,
            confidence_calibrated=confidence,
            stable_frames=self._stable_frames,
            duration_ms=duration_ms,
            hand_count=1,
            in_frame=True,
            hand_label=handedness,
            track_id=1,
            mirrored=False,
        )

    def _reset_stability(self) -> None:
        self._last_key = None
        self._stable_frames = 0
        self._stable_since_ns = None

    def _unknown(self, hand_count: int = 0) -> ClassifiedHand:
        return ClassifiedHand(
            gesture="unknown",
            confidence_raw=0.0,
            confidence_calibrated=0.0,
            stable_frames=0,
            duration_ms=0,
            hand_count=hand_count,
            in_frame=hand_count > 0,
            hand_label="unknown",
            track_id=0,
            mirrored=False,
        )


@dataclass
class OpenCVCameraSource:
    """Bounded local OpenCV webcam source. Frames are not persisted."""

    camera_index: int = 0
    width: int = 640
    height: int = 480
    max_frames: int = 120

    def frames(self):
        if self.max_frames < 1:
            raise ValueError("max_frames must be >= 1")
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV is not installed. Install requirements-uhip-mac.txt."
            ) from exc

        capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(
                f"Could not open local camera index {self.camera_index}. "
                "Check macOS camera permission and device availability."
            )

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        try:
            import time
            for frame_id in range(self.max_frames):
                ok, image = capture.read()
                if not ok:
                    raise RuntimeError("Camera frame read failed; stopping fail-closed.")
                yield CameraFrame(
                    frame_id=frame_id,
                    captured_mono_ns=time.monotonic_ns(),
                    width=int(image.shape[1]),
                    height=int(image.shape[0]),
                    data=image,
                )
        finally:
            capture.release()
