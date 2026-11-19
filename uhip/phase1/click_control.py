from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClickPolicy:
    """Fail-closed policy for one-shot local mouse clicks."""

    min_confidence: float = 0.95
    min_stable_frames: int = 5
    kill_switch_file: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.min_stable_frames < 1:
            raise ValueError("min_stable_frames must be >= 1")


@dataclass
class SafetyGateClickController:
    """Local left-click adapter with explicit arming and edge-triggered clicks.

    Recognition is not authorization. A click requires an explicit arm, a
    passing confidence/stability gate, and a fresh thumb-up gesture edge.
    Holding thumb-up therefore produces at most one click. STOP or the kill
    switch disarms the controller immediately.
    """

    policy: ClickPolicy
    armed: bool = False
    gate_passed: bool = False
    _thumb_active: bool = False
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

    def observe_thumb_up(self, *, confidence: float, stable_frames: int) -> bool:
        if (
            not self.armed
            or not self.gate_passed
            or self._kill_switch_active()
            or confidence < self.policy.min_confidence
            or stable_frames < self.policy.min_stable_frames
        ):
            self._thumb_active = False
            self.stop()
            return False

        if self._thumb_active:
            return False

        self._thumb_active = True
        self._post_left_click()
        return True

    def reset_gesture(self) -> None:
        self._thumb_active = False

    def stop(self) -> None:
        self.armed = False
        self.gate_passed = False
        self._thumb_active = False

    def _kill_switch_active(self) -> bool:
        path = self.policy.kill_switch_file
        return bool(path and Path(path).exists())

    def _post_left_click(self) -> None:
        if self._backend is None:
            try:
                import Quartz
            except ImportError as exc:
                raise RuntimeError(
                    "PyObjC Quartz is not installed; install the UHIP Mac requirements."
                ) from exc
            self._backend = Quartz

        current_event = self._backend.CGEventCreate(None)
        point = self._backend.CGEventGetLocation(current_event)
        down = self._backend.CGEventCreateMouseEvent(
            None, self._backend.kCGEventLeftMouseDown, point, self._backend.kCGMouseButtonLeft
        )
        up = self._backend.CGEventCreateMouseEvent(
            None, self._backend.kCGEventLeftMouseUp, point, self._backend.kCGMouseButtonLeft
        )
        self._backend.CGEventPost(self._backend.kCGHIDEventTap, down)
        self._backend.CGEventPost(self._backend.kCGHIDEventTap, up)
