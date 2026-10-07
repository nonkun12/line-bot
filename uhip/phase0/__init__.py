"""UHIP Phase 0 safe, local-only recognition core."""

from .camera_adapter import CameraAdapter, CameraFrame, ClassifiedHand, bounded_frames
from .mediapipe_camera import (
    MediaPipeGestureClassifier,
    OpenCVCameraSource,
    verify_model_sha256,
)
from .recognizer import GatePolicy, Observation, RecognitionResult, recognize
from .replay import ReplayResult, replay_lines

__all__ = [
    "CameraAdapter",
    "CameraFrame",
    "ClassifiedHand",
    "GatePolicy",
    "MediaPipeGestureClassifier",
    "Observation",
    "OpenCVCameraSource",
    "RecognitionResult",
    "ReplayResult",
    "bounded_frames",
    "recognize",
    "replay_lines",
    "verify_model_sha256",
]
