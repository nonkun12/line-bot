from __future__ import annotations

from dataclasses import dataclass

import pytest

from uhip.phase0.hand_position import (
    HandPosition,
    normalized_palm_position,
    screen_candidate,
)


@dataclass
class Landmark:
    x: float
    y: float


def landmarks(x: float = 0.25, y: float = 0.40) -> list[Landmark]:
    points = [Landmark(x, y) for _ in range(21)]
    return points


def test_normalized_palm_position_uses_palm_points() -> None:
    points = landmarks()
    points[0] = Landmark(0.10, 0.20)
    points[5] = Landmark(0.20, 0.30)
    points[9] = Landmark(0.30, 0.40)
    points[13] = Landmark(0.40, 0.50)
    points[17] = Landmark(0.50, 0.60)

    position = normalized_palm_position(points)

    assert position == HandPosition(0.30, 0.40)


def test_invalid_landmark_count_fails_closed() -> None:
    assert normalized_palm_position([]) is None


def test_screen_candidate_is_bounded() -> None:
    assert screen_candidate(HandPosition(0.0, 0.0), width=100, height=80) == (0, 0)
    assert screen_candidate(HandPosition(1.0, 1.0), width=100, height=80) == (99, 79)


def test_screen_candidate_can_mirror_x_without_side_effect() -> None:
    assert screen_candidate(
        HandPosition(0.25, 0.50),
        width=100,
        height=80,
        mirrored=True,
    ) == (74, 40)


def test_screen_candidate_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError):
        screen_candidate(HandPosition(0.5, 0.5), width=0, height=80)
