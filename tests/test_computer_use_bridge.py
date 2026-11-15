from __future__ import annotations

import pytest

from core.computer_use_bridge import (
    ApprovalError,
    LocalComputerUseBridge,
    approve_plan,
)
from core.desktop_control import DesktopExecutionDisabled, validate_plan


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"mode": "read-only"}

    def act(self, app, operation, params):
        self.calls.append((app, operation, params))
        return {"ok": True, "operation": operation}


def _plan():
    return validate_plan({
        "schema_version": 1,
        "app": "excel",
        "goal": "test",
        "actions": [{
            "id": "a1",
            "operation": "write_cells",
            "params": {"sheet_name": "Sheet1", "range": "A1", "values": [[42]]},
        }],
    }, original_request="Excelを操作して")


def test_bridge_is_disabled_by_default():
    bridge = LocalComputerUseBridge()
    with pytest.raises(DesktopExecutionDisabled, match="trusted_local_approval_ui_not_connected"):
        bridge.snapshot()
    with pytest.raises(DesktopExecutionDisabled, match="trusted_local_approval_ui_not_connected"):
        bridge.execute(_plan())


def test_enabled_flag_and_injected_adapter_do_not_bypass_trusted_approval_gate():
    adapter = FakeAdapter()
    bridge = LocalComputerUseBridge(adapter, enabled=True)
    with pytest.raises(DesktopExecutionDisabled, match="trusted_local_approval_ui_not_connected"):
        bridge.snapshot()
    with pytest.raises(DesktopExecutionDisabled, match="trusted_local_approval_ui_not_connected"):
        bridge.execute(_plan(), grant=object())
    assert adapter.calls == []


def test_confirmation_string_is_not_accepted_as_human_approval():
    with pytest.raises(ApprovalError, match="trusted_local_approval_ui_not_connected"):
        approve_plan(_plan(), confirmation="この操作計画を承認する")


def test_no_adapter_side_effects_are_possible_through_placeholder():
    adapter = FakeAdapter()
    bridge = LocalComputerUseBridge(adapter, enabled=True)
    with pytest.raises(DesktopExecutionDisabled):
        bridge.execute(_plan(), grant=object())
    assert adapter.calls == []
