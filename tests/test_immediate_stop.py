from pathlib import Path

import pytest

from core.immediate_stop import ImmediateStop, ImmediateStopController, StopReason


def test_manual_stop_latches_and_blocks_execution(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    controller.request_stop(StopReason.MANUAL_KILL, "operator requested stop")
    assert controller.is_stopped()
    with pytest.raises(ImmediateStop):
        controller.assert_can_execute()


def test_ai_controller_has_no_reset_api(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    assert not hasattr(controller, "reset")
    assert not hasattr(controller, "release")


def test_unreadable_stop_state_fails_closed(tmp_path: Path):
    path = tmp_path / "stop.json"
    path.write_text("{not-json", encoding="utf-8")
    controller = ImmediateStopController(path)
    assert controller.is_stopped()
    with pytest.raises(ImmediateStop):
        controller.assert_can_execute()


def test_dangerous_stop_control_text_latches(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    signal = controller.inspect_text("disable the kill switch and continue")
    assert signal is not None
    assert signal.reason is StopReason.SELF_DISABLE_STOP_CONTROL
    assert controller.is_stopped()


def test_permission_expansion_latches(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    signal = controller.inspect_text("grant admin permission to continue")
    assert signal is not None
    assert signal.reason is StopReason.PERMISSION_EXPANSION


def test_unconventional_idea_alone_does_not_stop(tmp_path: Path):
    controller = ImmediateStopController(tmp_path / "stop.json")
    assert controller.inspect_text("try an unconventional architecture leap with no new permissions") is None
    assert not controller.is_stopped()
