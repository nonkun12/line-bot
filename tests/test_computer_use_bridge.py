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


def _plan(operation="write_cells"):
    params = {
        "sheet_name": "Sheet1",
        "range": "A1",
        "values": [[42]],
    } if operation == "write_cells" else {}
    return validate_plan({
        "schema_version": 1,
        "app": "excel",
        "goal": "test",
        "actions": [{"id": "a1", "operation": operation, "params": params}],
    }, original_request="Excelを操作して")


def test_bridge_is_disabled_by_default():
    bridge = LocalComputerUseBridge()
    with pytest.raises(DesktopExecutionDisabled):
        bridge.snapshot()
    with pytest.raises(DesktopExecutionDisabled):
        bridge.execute(_plan())


def test_requires_explicit_confirmation_phrase():
    with pytest.raises(ApprovalError, match="explicit_confirmation_required"):
        approve_plan(_plan(), confirmation="はい")


def test_grant_is_bound_to_plan_and_consumed_once():
    plan = _plan()
    adapter = FakeAdapter()
    bridge = LocalComputerUseBridge(adapter, enabled=True)
    grant = approve_plan(plan, confirmation="この操作計画を承認する", now=100)
    result = bridge.execute(plan, grant, now=101)
    assert result == [{"ok": True, "operation": "write_cells"}]
    assert len(adapter.calls) == 1
    with pytest.raises(ApprovalError, match="approval_already_consumed"):
        bridge.execute(plan, grant, now=102)


def test_grant_cannot_be_reused_for_another_plan():
    plan = _plan()
    other_plan = validate_plan({
        "schema_version": 1,
        "app": "excel",
        "goal": "different",
        "actions": [{"id": "a1", "operation": "inspect_sheet", "params": {}}],
    }, original_request="別の計画")
    grant = approve_plan(plan, confirmation="この操作計画を承認する", now=10)
    bridge = LocalComputerUseBridge(FakeAdapter(), enabled=True)
    with pytest.raises(ApprovalError, match="plan_digest_mismatch"):
        bridge.execute(other_plan, grant, now=11)


def test_expired_grant_is_rejected():
    plan = _plan()
    grant = approve_plan(plan, confirmation="この操作計画を承認する", now=10, ttl_seconds=30)
    bridge = LocalComputerUseBridge(FakeAdapter(), enabled=True)
    with pytest.raises(ApprovalError, match="approval_expired"):
        bridge.execute(plan, grant, now=41)


def test_partial_execution_failure_still_consumes_grant():
    plan = _plan()
    class BrokenAdapter(FakeAdapter):
        def act(self, app, operation, params):
            raise RuntimeError("adapter failed")
    grant = approve_plan(plan, confirmation="この操作計画を承認する", now=10)
    bridge = LocalComputerUseBridge(BrokenAdapter(), enabled=True)
    with pytest.raises(RuntimeError):
        bridge.execute(plan, grant, now=11)
    assert grant.consumed is True
