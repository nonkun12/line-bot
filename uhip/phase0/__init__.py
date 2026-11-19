"""UHIP Phase 0 safe, local-only recognition core."""

from .camera_adapter import CameraAdapter, CameraFrame, ClassifiedHand, bounded_frames
from .hand_position import HandPosition, normalized_palm_position, screen_candidate
from .mediapipe_camera import MediaPipeHandsClassifier, OpenCVCameraSource, classify_landmarks
from .recognizer import GatePolicy, Observation, RecognitionResult, recognize
from .replay import ReplayResult, replay_lines

__all__ = [
    "CameraAdapter",
    "CameraFrame",
    "ClassifiedHand",
    "GatePolicy",
    "HandPosition",
    "MediaPipeHandsClassifier",
    "Observation",
    "OpenCVCameraSource",
    "RecognitionResult",
    "ReplayResult",
    "bounded_frames",
    "classify_landmarks",
    "recognize",
    "replay_lines",
    "normalized_palm_position",
    "screen_candidate",
]
