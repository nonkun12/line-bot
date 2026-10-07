from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class HandPosition:
    """Normalized palm position used as a non-actionable cursor candidate."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("hand position must be finite")
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("hand position must be normalized to [0, 1]")


def normalized_palm_position(landmarks: list[object]) -> HandPosition | None:
    """Return a stable palm-center candidate from MediaPipe landmarks.

    Uses wrist (0) and the four MCP joints (5, 9, 13, 17). This is only a
    coordinate candidate; it authorizes no OS input and performs no side effect.
    """
    if len(landmarks) != 21:
        return None

    points = [landmarks[index] for index in (0, 5, 9, 13, 17)]
    try:
        x = sum(float(point.x) for point in points) / len(points)
        y = sum(float(point.y) for point in points) / len(points)
    except (AttributeError, TypeError, ValueError):
        return None

    try:
        return HandPosition(x=x, y=y)
    except ValueError:
        return None


def screen_candidate(
    position: HandPosition,
    *,
    width: int,
    height: int,
    mirrored: bool = False,
) -> tuple[int, int]:
    """Map normalized hand position to a bounded screen candidate.

    This function only calculates coordinates. It never moves the OS cursor.
    """
    if width < 1 or height < 1:
        raise ValueError("screen dimensions must be >= 1")

    x = 1.0 - position.x if mirrored else position.x
    x_px = min(width - 1, max(0, round(x * (width - 1))))
    y_px = min(height - 1, max(0, round(position.y * (height - 1))))
    return x_px, y_px
