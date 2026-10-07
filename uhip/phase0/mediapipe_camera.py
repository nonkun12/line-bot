from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .camera_adapter import CameraFrame, ClassifiedHand


_GESTURE_MAP = {
    "Thumb_Up": "thumb_up",
    "Open_Palm": "open_palm",
    "Closed_Fist": "fist",
}


def verify_model_sha256(model_path: str | Path, expected_sha256: str) -> str:
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"MediaPipe model not found: {path}")
    actual = sha256(path.read_bytes()).hexdigest()
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or actual != expected:
        raise ValueError(
            f"MediaPipe model SHA-256 mismatch: expected={expected} actual={actual}"
        )
    return actual


def _unknown_result(hand_count: int = 0, hand_label: str = "unknown") -> ClassifiedHand:
    return ClassifiedHand(
        gesture="unknown",
        confidence_raw=0.0,
        confidence_calibrated=0.0,
        stable_frames=0,
        duration_ms=0,
        hand_count=hand_count,
        in_frame=hand_count > 0,
        hand_label=hand_label,
        track_id=0,
        mirrored=False,
    )


@dataclass
class MediaPipeGestureClassifier:
    """Local MediaPipe Gesture Recognizer adapter.

    This class only translates model output into ClassifiedHand. Authorization
    remains in the existing UHIP Recognition Gate.
    """

    model_path: str
    expected_model_sha256: str
    min_model_confidence: float = 0.50
    _recognizer: object | None = field(default=None, init=False, repr=False)
    _last_key: tuple[str, str] | None = field(default=None, init=False, repr=False)
    _stable_frames: int = field(default=0, init=False, repr=False)
    _stable_since_ns: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_model_confidence <= 1.0:
            raise ValueError("min_model_confidence must be between 0 and 1")
        verify_model_sha256(self.model_path, self.expected_model_sha256)

        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError(
                "MediaPipe is not installed. Install requirements-uhip-mac.txt."
            ) from exc

        base_options = mp.tasks.BaseOptions(model_asset_path=self.model_path)
        options = mp.tasks.vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=self.min_model_confidence,
            min_hand_presence_confidence=self.min_model_confidence,
            min_tracking_confidence=self.min_model_confidence,
        )
        self._recognizer = mp.tasks.vision.GestureRecognizer.create_from_options(options)

    def close(self) -> None:
        recognizer = self._recognizer
        if recognizer is not None:
            recognizer.close()
            self._recognizer = None

    def classify(self, frame: CameraFrame) -> ClassifiedHand:
        if self._recognizer is None:
            raise RuntimeError("MediaPipe recognizer is closed")

        try:
            import mediapipe as mp
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "MediaPipe and NumPy are required for local classification."
            ) from exc

        if frame.data is None:
            return _unknown_result()

        image = np.asarray(frame.data)
        if image.ndim != 3 or image.shape[2] != 3:
            return _unknown_result()

        rgb = image[:, :, ::-1].copy()
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = frame.captured_mono_ns // 1_000_000
        result = self._recognizer.recognize_for_video(mp_image, timestamp_ms)

        hand_count = len(result.hand_landmarks)
        if hand_count == 0:
            self._reset_stability()
            return _unknown_result()

        handedness = "unknown"
        if result.handedness and result.handedness[0]:
            handedness = str(result.handedness[0][0].category_name or "unknown").lower()
            if handedness not in {"left", "right"}:
                handedness = "unknown"

        gesture_name = "unknown"
        gesture_score = 0.0
        if result.gestures and result.gestures[0]:
            category = result.gestures[0][0]
            gesture_name = str(category.category_name or "unknown")
            gesture_score = float(category.score or 0.0)

        mapped_gesture = _GESTURE_MAP.get(gesture_name, "unknown")
        if gesture_score < self.min_model_confidence:
            mapped_gesture = "unknown"

        if hand_count != 1:
            self._reset_stability()
            return ClassifiedHand(
                gesture=mapped_gesture,
                confidence_raw=gesture_score,
                confidence_calibrated=gesture_score,
                stable_frames=0,
                duration_ms=0,
                hand_count=hand_count,
                in_frame=True,
                hand_label=handedness,
                track_id=0,
                mirrored=False,
            )

        key = (mapped_gesture, handedness)
        if mapped_gesture == "unknown":
            self._reset_stability()
            return ClassifiedHand(
                gesture="unknown",
                confidence_raw=gesture_score,
                confidence_calibrated=gesture_score,
                stable_frames=0,
                duration_ms=0,
                hand_count=1,
                in_frame=True,
                hand_label=handedness,
                track_id=1,
                mirrored=False,
            )

        if key == self._last_key:
            self._stable_frames += 1
        else:
            self._last_key = key
            self._stable_frames = 1
            self._stable_since_ns = frame.captured_mono_ns

        started_ns = self._stable_since_ns or frame.captured_mono_ns
        duration_ms = max(0, (frame.captured_mono_ns - started_ns) // 1_000_000)

        return ClassifiedHand(
            gesture=mapped_gesture,
            confidence_raw=gesture_score,
            confidence_calibrated=gesture_score,
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


@dataclass
class OpenCVCameraSource:
    """Bounded, local OpenCV webcam source. Frames are not persisted."""

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
