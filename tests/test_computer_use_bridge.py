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


from core.desktop_approval_policy import (
    ApprovalCapability,
    CapabilityPolicyError,
    validate_capability,
)


def _capability(plan, *, action_ids=("a1",), session_id="mac-session-A",
                issued_at=1000.0, expires_at=1060.0, nonce="n" * 40):
    return ApprovalCapability(
        plan_sha256=plan.plan_sha256,
        action_ids=action_ids,
        session_id=session_id,
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce,
    )


def test_capability_accepts_only_selected_action_scope_once():
    plan = validate_plan({
        "schema_version": 1, "app": "excel", "goal": "Two writes",
        "actions": [
            {"id": "a1", "operation": "write_cells",
             "params": {"sheet_name": "S", "range": "A1", "values": [[1]]}},
            {"id": "a2", "operation": "write_cells",
             "params": {"sheet_name": "S", "range": "A2", "values": [[2]]}},
        ],
    }, original_request="2セル入力")
    capability = _capability(plan, action_ids=("a2",))
    redeemed = set()
    assert validate_capability(
        capability, plan, current_session_id="mac-session-A",
        now=1010.0, redeemed_nonces=redeemed,
    ) == ("a2",)
    with pytest.raises(CapabilityPolicyError, match="capability_replayed"):
        validate_capability(
            capability, plan, current_session_id="mac-session-A",
            now=1011.0, redeemed_nonces=redeemed,
        )


def test_capability_rejects_action_ids_outside_plan_or_wrong_order():
    plan = validate_plan({
        "schema_version": 1, "app": "excel", "goal": "Two reads",
        "actions": [
            {"id": "a1", "operation": "inspect_sheet", "params": {"sheet_name": "A"}},
            {"id": "a2", "operation": "inspect_sheet", "params": {"sheet_name": "B"}},
        ],
    }, original_request="2枚確認")
    for ids in (("unknown",), ("a2", "a1")):
        with pytest.raises(CapabilityPolicyError, match="action_scope_mismatch"):
            validate_capability(
                _capability(plan, action_ids=ids, nonce=("x" if ids[0] == "unknown" else "y") * 40),
                plan, current_session_id="mac-session-A",
                now=1010.0, redeemed_nonces=set(),
            )


def test_capability_rejects_session_mismatch_and_expiry():
    plan = _plan()
    with pytest.raises(CapabilityPolicyError, match="session_mismatch"):
        validate_capability(
            _capability(plan), plan, current_session_id="different-session",
            now=1010.0, redeemed_nonces=set(),
        )
    with pytest.raises(CapabilityPolicyError, match="capability_expired_or_not_yet_valid"):
        validate_capability(
            _capability(plan, nonce="e" * 40), plan,
            current_session_id="mac-session-A", now=1060.0,
            redeemed_nonces=set(),
        )


def test_capability_rejects_lifetime_over_two_minutes_and_digest_mismatch():
    plan = _plan()
    with pytest.raises(CapabilityPolicyError, match="invalid_capability_lifetime"):
        validate_capability(
            _capability(plan, expires_at=1121.0), plan,
            current_session_id="mac-session-A", now=1010.0,
            redeemed_nonces=set(),
        )
    other_plan = validate_plan({
        "schema_version": 1, "app": "excel", "goal": "different",
        "actions": [{"id": "a1", "operation": "inspect_sheet", "params": {}}],
    }, original_request="different")
    with pytest.raises(CapabilityPolicyError, match="plan_digest_mismatch"):
        validate_capability(
            _capability(plan), other_plan,
            current_session_id="mac-session-A", now=1010.0,
            redeemed_nonces=set(),
        )


def test_capability_rejects_duplicate_and_malformed_action_ids():
    plan = _plan()
    for ids, nonce in [(("a1", "a1"), "d" * 40), (("",), "m" * 40)]:
        with pytest.raises(CapabilityPolicyError):
            validate_capability(
                _capability(plan, action_ids=ids, nonce=nonce), plan,
                current_session_id="mac-session-A", now=1010.0,
                redeemed_nonces=set(),
            )


@pytest.mark.parametrize("issued_at,expires_at,now", [
    (True, 1060.0, 1010.0),
    (1000.0, False, 1010.0),
    (1000.0, 1060.0, float("nan")),
    (1000.0, 1060.0, 999.0),
])
def test_capability_rejects_invalid_or_not_yet_valid_timestamps(issued_at, expires_at, now):
    plan = _plan()
    with pytest.raises(CapabilityPolicyError):
        validate_capability(
            _capability(plan, issued_at=issued_at, expires_at=expires_at, nonce="t" * 40),
            plan, current_session_id="mac-session-A", now=now,
            redeemed_nonces=set(),
        )
