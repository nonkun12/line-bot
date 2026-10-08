from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from uhip.phase0.hand_position import HandPosition, screen_candidate


class CursorController(Protocol):
    def move(self, position: HandPosition) -> bool:
        """Move the local cursor only when the implementation is explicitly armed."""

    def stop(self) -> None:
        """Immediately disarm and prevent further movement."""


@dataclass(frozen=True)
class CursorPolicy:
    """Fail-closed policy for Phase 1-C cursor movement."""

    min_confidence: float = 0.95
    min_stable_frames: int = 5
    screen_width: int = 1920
    screen_height: int = 1080
    dead_zone_px: int = 6
    smoothing: float = 0.35
    kill_switch_file: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.min_stable_frames < 1:
            raise ValueError("min_stable_frames must be >= 1")
        if self.screen_width < 1 or self.screen_height < 1:
            raise ValueError("screen dimensions must be >= 1")
        if self.dead_zone_px < 0:
            raise ValueError("dead_zone_px must be >= 0")
        if not 0.0 < self.smoothing <= 1.0:
            raise ValueError("smoothing must be > 0 and <= 1")


@dataclass
class SafetyGateCursorController:
    """Local cursor adapter with explicit arming and fail-closed gates.

    Recognition is not authorization. The caller must provide a passed gate,
    and this controller must be explicitly armed. No clicks or keyboard input
    are implemented here. A kill-switch file disarms the controller immediately.
    """

    policy: CursorPolicy
    armed: bool = False
    gate_passed: bool = False
    _last_xy: tuple[float, float] | None = None
    _backend: object | None = None

    def arm(self, gate_passed: bool) -> bool:
        if self._kill_switch_active() or not gate_passed:
            self.stop()
            return False
        self.gate_passed = True
        self.armed = True
        return True

    def update_gate(self, gate_passed: bool) -> None:
        if not gate_passed or self._kill_switch_active():
            self.stop()
        else:
            self.gate_passed = True

    def move(self, position: HandPosition) -> bool:
        if not self.armed or not self.gate_passed or self._kill_switch_active():
            self.stop()
            return False
        target = screen_candidate(
            position,
            width=self.policy.screen_width,
            height=self.policy.screen_height,
        )
        if self._last_xy is None:
            smoothed = (float(target[0]), float(target[1]))
        else:
            a = self.policy.smoothing
            smoothed = (
                self._last_xy[0] + (target[0] - self._last_xy[0]) * a,
                self._last_xy[1] + (target[1] - self._last_xy[1]) * a,
            )
        if self._last_xy is not None:
            dx = smoothed[0] - self._last_xy[0]
            dy = smoothed[1] - self._last_xy[1]
            if (dx * dx + dy * dy) ** 0.5 < self.policy.dead_zone_px:
                return False
        self._last_xy = smoothed
        self._warp_cursor(round(smoothed[0]), round(smoothed[1]))
        return True

    def stop(self) -> None:
        self.armed = False
        self.gate_passed = False
        self._last_xy = None

    def _kill_switch_active(self) -> bool:
        path = self.policy.kill_switch_file
        return bool(path and Path(path).exists())

    def _warp_cursor(self, x: int, y: int) -> None:
        if self._backend is None:
            try:
                import Quartz
            except ImportError as exc:
                raise RuntimeError(
                    "PyObjC Quartz is not installed; install the UHIP Mac requirements."
                ) from exc
            self._backend = Quartz
        self._backend.CGWarpMouseCursorPosition((x, y))
