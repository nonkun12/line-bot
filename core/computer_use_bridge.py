"""Fail-closed approval gate for a future Mac-local Computer Use adapter.

This module does not connect to OpenClaw or operate a desktop. It defines the
narrow boundary that a separately reviewed local adapter must implement.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from core.desktop_control import DesktopPlan, DesktopExecutionDisabled


class ApprovalError(RuntimeError):
    """An approval is absent, expired, mismatched, or already consumed."""


class ComputerUseAdapter(Protocol):
    """Minimal local adapter contract; implementations must not expose shell access."""

    def snapshot(self) -> Any:
        """Return a bounded screenshot/accessibility snapshot without changing state."""

    def act(self, app: str, operation: str, params: dict[str, Any]) -> Any:
        """Execute exactly one validated operation in the foreground application."""


@dataclass
class ApprovalGrant:
    plan_sha256: str
    action_ids: frozenset[str]
    expires_at: float
    nonce: str
    consumed: bool = False


def approve_plan(
    plan: DesktopPlan,
    *,
    confirmation: str,
    action_ids: set[str] | None = None,
    ttl_seconds: int = 120,
    now: float | None = None,
) -> ApprovalGrant:
    """Issue a short-lived, one-use grant after an explicit UI confirmation."""
    if confirmation != "この操作計画を承認する":
        raise ApprovalError("explicit_confirmation_required")
    if not isinstance(plan, DesktopPlan) or not plan.actions:
        raise ApprovalError("invalid_plan")
    if not 1 <= ttl_seconds <= 300:
        raise ApprovalError("invalid_approval_ttl")
    available = {action["id"] for action in plan.actions}
    selected = available if action_ids is None else set(action_ids)
    if not selected or not selected.issubset(available):
        raise ApprovalError("approval_action_scope_invalid")
    return ApprovalGrant(
        plan_sha256=plan.plan_sha256,
        action_ids=frozenset(selected),
        expires_at=(time.time() if now is None else now) + ttl_seconds,
        nonce=secrets.token_urlsafe(24),
    )


class LocalComputerUseBridge:
    """Default-deny bridge. A live adapter must be explicitly injected and enabled."""

    def __init__(self, adapter: ComputerUseAdapter | None = None, *, enabled: bool = False):
        self._adapter = adapter
        self._enabled = enabled

    def snapshot(self) -> Any:
        if not self._enabled or self._adapter is None:
            raise DesktopExecutionDisabled("computer_use_bridge_disabled")
        return self._adapter.snapshot()

    def execute(
        self,
        plan: DesktopPlan,
        grant: ApprovalGrant | None = None,
        *,
        now: float | None = None,
    ) -> list[Any]:
        if not self._enabled or self._adapter is None:
            raise DesktopExecutionDisabled("computer_use_bridge_disabled")
        if not isinstance(plan, DesktopPlan) or grant is None:
            raise ApprovalError("approval_required")
        current = time.time() if now is None else now
        if grant.consumed:
            raise ApprovalError("approval_already_consumed")
        if current > grant.expires_at:
            raise ApprovalError("approval_expired")
        if not secrets.compare_digest(grant.plan_sha256, plan.plan_sha256):
            raise ApprovalError("plan_digest_mismatch")

        actions = [a for a in plan.actions if a["id"] in grant.action_ids]
        if len(actions) != len(grant.action_ids):
            raise ApprovalError("approval_action_scope_mismatch")
        if not actions:
            raise ApprovalError("empty_approval_scope")
        if any(a["risk"] != "read_only" for a in actions):
            # A grant can authorize edits only when the plan explicitly requested
            # confirmation; the confirmation phrase above is the human gate.
            if not plan.requires_human_confirmation:
                raise ApprovalError("plan_confirmation_state_invalid")

        # Consume before the first external side effect. A partial failure cannot
        # be retried with the same grant; the user must review and approve again.
        grant.consumed = True
        results = []
        for action in actions:
            results.append(self._adapter.act(
                plan.app, action["operation"], dict(action["params"])
            ))
        return results


def plan_fingerprint(plan: DesktopPlan) -> str:
    """Independent fingerprint helper for audit/log correlation."""
    return hashlib.sha256(plan.plan_sha256.encode("ascii")).hexdigest()


__all__ = [
    "ApprovalError", "ApprovalGrant", "ComputerUseAdapter",
    "LocalComputerUseBridge", "approve_plan", "plan_fingerprint",
]
