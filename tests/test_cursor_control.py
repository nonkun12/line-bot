from __future__ import annotations

from pathlib import Path

from uhip.phase0.hand_position import HandPosition
from uhip.phase1.cursor_control import CursorPolicy, SafetyGateCursorController


class FakeBackend:
    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []

    def CGWarpMouseCursorPosition(self, point: tuple[int, int]) -> None:
        self.moves.append(point)


def controller(**kwargs: object) -> tuple[SafetyGateCursorController, FakeBackend]:
    backend = FakeBackend()
    item = SafetyGateCursorController(CursorPolicy(**kwargs))
    item._backend = backend
    return item, backend


def test_disarmed_by_default_and_gate_required() -> None:
    item, backend = controller()
    assert item.armed is False
    assert item.move(HandPosition(0.5, 0.5)) is False
    assert backend.moves == []
    assert item.arm(False) is False
    assert item.move(HandPosition(0.5, 0.5)) is False
    assert backend.moves == []


def test_armed_gate_pass_moves_cursor() -> None:
    item, backend = controller(smoothing=1.0, dead_zone_px=0)
    assert item.arm(True) is True
    assert item.move(HandPosition(0.5, 0.5)) is True
    assert backend.moves == [(960, 540)]


def test_gate_failure_immediately_stops() -> None:
    item, backend = controller(smoothing=1.0, dead_zone_px=0)
    assert item.arm(True) is True
    item.update_gate(False)
    assert item.move(HandPosition(0.8, 0.8)) is False
    assert backend.moves == []


def test_kill_switch_immediately_stops(tmp_path: Path) -> None:
    kill = tmp_path / "UHIP_KILL"
    item, backend = controller(smoothing=1.0, dead_zone_px=0, kill_switch_file=str(kill))
    assert item.arm(True) is True
    kill.touch()
    assert item.move(HandPosition(0.8, 0.8)) is False
    assert item.armed is False
    assert backend.moves == []


def test_dead_zone_suppresses_small_motion() -> None:
    item, backend = controller(smoothing=1.0, dead_zone_px=10)
    assert item.arm(True) is True
    assert item.move(HandPosition(0.5, 0.5)) is True
    assert item.move(HandPosition(0.502, 0.502)) is False
    assert len(backend.moves) == 1


def test_stop_disarms() -> None:
    item, backend = controller(smoothing=1.0, dead_zone_px=0)
    assert item.arm(True) is True
    item.stop()
    assert item.armed is False
    assert item.move(HandPosition(0.9, 0.9)) is False
    assert backend.moves == []
