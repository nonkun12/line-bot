"""Pure policy checks for a future trusted local approval broker.

This module does not authenticate callers, mint capabilities, provide IPC, or enable
desktop execution. A capability instance is untrusted data until a separately
reviewed OS-session-bound broker exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import MutableSet

from core.desktop_control import DesktopPlan

MAX_CAPABILITY_LIFETIME_SECONDS = 120


class CapabilityPolicyError(ValueError):
    """A proposed approval capability violates the local approval policy."""


@dataclass(frozen=True)
class ApprovalCapability:
    plan_sha256: str
    action_ids: tuple[str, ...]
    session_id: str
    issued_at: float
    expires_at: float
    nonce: str


def validate_capability(
    capability: ApprovalCapability,
    plan: DesktopPlan,
    *,
    current_session_id: str,
    now: float,
    redeemed_nonces: MutableSet[str],
) -> tuple[str, ...]:
    """Validate scope, session, expiry and one-use state; never grants execution."""
    if not isinstance(capability, ApprovalCapability):
        raise CapabilityPolicyError("invalid_capability_type")
    if capability.plan_sha256 != plan.plan_sha256:
        raise CapabilityPolicyError("plan_digest_mismatch")
    if not isinstance(capability.action_ids, tuple) or not capability.action_ids:
        raise CapabilityPolicyError("invalid_action_scope")
    allowed_ids = tuple(action["id"] for action in plan.actions)
    selected = capability.action_ids
    if len(set(selected)) != len(selected):
        raise CapabilityPolicyError("duplicate_action_scope")
    positions = [allowed_ids.index(action_id) if action_id in allowed_ids else -1 for action_id in selected]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise CapabilityPolicyError("action_scope_mismatch")
    if not isinstance(capability.session_id, str) or not capability.session_id:
        raise CapabilityPolicyError("invalid_session_binding")
    if capability.session_id != current_session_id:
        raise CapabilityPolicyError("session_mismatch")
    times = (capability.issued_at, capability.expires_at, now)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in times):
        raise CapabilityPolicyError("invalid_capability_time")
    lifetime = capability.expires_at - capability.issued_at
    if lifetime <= 0 or lifetime > MAX_CAPABILITY_LIFETIME_SECONDS:
        raise CapabilityPolicyError("invalid_capability_lifetime")
    if now < capability.issued_at or now >= capability.expires_at:
        raise CapabilityPolicyError("capability_expired_or_not_yet_valid")
    if not isinstance(capability.nonce, str) or len(capability.nonce) < 32:
        raise CapabilityPolicyError("invalid_capability_nonce")
    if capability.nonce in redeemed_nonces:
        raise CapabilityPolicyError("capability_replayed")
    redeemed_nonces.add(capability.nonce)
    return selected


__all__ = ["ApprovalCapability", "CapabilityPolicyError", "validate_capability"]
