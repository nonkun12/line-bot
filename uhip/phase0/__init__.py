"""UHIP Phase 0 safe, local-only recognition core."""

from .recognizer import GatePolicy, Observation, RecognitionResult, recognize
from .replay import ReplayResult, replay_lines

__all__ = [
    "GatePolicy",
    "Observation",
    "RecognitionResult",
    "ReplayResult",
    "recognize",
    "replay_lines",
]
