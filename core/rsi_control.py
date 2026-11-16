"""Verified, freshness-bounded RSI control snapshots.

No environment variable or unsigned dashboard text is treated as authority.
A deployment must inject a trusted snapshot source and signature verifier. If
either is absent, invalid, stale, replayed, or FREE-budget-unknown, access fails.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Callable

from .rsi_executor import EvidenceLedger, RSIControl, RSIError, canonical_digest, _bounded_id


@dataclass(frozen=True)
class SignedRSIControlSnapshot:
    global_hold: bool
    execution_enabled: bool
    free_only: bool
    budget_known: bool
    budget_remaining_units: int
    paid_fallback_enabled: bool
    issued_at: int
    expires_at: int
    nonce: str
    signature: str


class VerifiedRSIControlProvider:
    def __init__(
        self,
        snapshot_source: Callable[[], SignedRSIControlSnapshot],
        *,
        verify_signature: Callable[[str, str], bool],
        ledger: EvidenceLedger,
        max_age_seconds: int = 120,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(snapshot_source) or not callable(verify_signature):
            raise TypeError("trusted snapshot source and signature verifier are required")
        if type(max_age_seconds) is not int or not 10 <= max_age_seconds <= 300:
            raise ValueError("control snapshot age must be 10..300 seconds")
        self._source = snapshot_source
        self._verify = verify_signature
        self._ledger = ledger
        self._max_age = max_age_seconds
        self._clock = clock
        self._last_nonce: str | None = None
        self._last_digest: str | None = None

    def __call__(self) -> RSIControl:
        snapshot = self._source()
        if not isinstance(snapshot, SignedRSIControlSnapshot):
            raise RSIError("trusted RSI control snapshot unavailable")
        bool_fields = (
            snapshot.global_hold, snapshot.execution_enabled, snapshot.free_only,
            snapshot.budget_known, snapshot.paid_fallback_enabled,
        )
        if any(type(value) is not bool for value in bool_fields):
            raise RSIError("control snapshot boolean fields are invalid")
        if (type(snapshot.budget_remaining_units) is not int
                or not 0 <= snapshot.budget_remaining_units <= 1_000_000):
            raise RSIError("FREE budget snapshot is invalid")
        if (type(snapshot.issued_at) is not int or type(snapshot.expires_at) is not int
                or snapshot.expires_at <= snapshot.issued_at):
            raise RSIError("control snapshot time bounds are invalid")
        _bounded_id(snapshot.nonce, "control snapshot nonce")
        if not isinstance(snapshot.signature, str) or not snapshot.signature.strip():
            raise RSIError("control snapshot signature is missing")

        now = int(self._clock())
        if snapshot.issued_at > now + 30 or now - snapshot.issued_at > self._max_age:
            raise RSIError("control snapshot is stale or issued in the future")
        if now >= snapshot.expires_at or snapshot.expires_at - snapshot.issued_at > self._max_age:
            raise RSIError("control snapshot is expired or overlong")
        signed = {
            "global_hold": snapshot.global_hold,
            "execution_enabled": snapshot.execution_enabled,
            "free_only": snapshot.free_only,
            "budget_known": snapshot.budget_known,
            "budget_remaining_units": snapshot.budget_remaining_units,
            "paid_fallback_enabled": snapshot.paid_fallback_enabled,
            "issued_at": snapshot.issued_at,
            "expires_at": snapshot.expires_at,
            "nonce": snapshot.nonce,
        }
        digest = canonical_digest(signed)
        if not self._verify(digest, snapshot.signature):
            raise RSIError("control snapshot signature verification failed")
        if self._last_nonce == snapshot.nonce:
            if self._last_digest != digest:
                raise RSIError("control snapshot nonce was reused with different content")
        else:
            self._ledger.append(
                "control-snapshot:" + snapshot.nonce,
                "verified_control_snapshot",
                {"digest": digest, "issued_at": snapshot.issued_at},
            )
            self._last_nonce, self._last_digest = snapshot.nonce, digest

        # Unknown budget is carried as unknown; RSIExecutor._control blocks it.
        return RSIControl(
            snapshot.global_hold,
            snapshot.execution_enabled,
            snapshot.free_only,
            snapshot.budget_known,
            snapshot.budget_remaining_units,
            snapshot.paid_fallback_enabled,
        )


__all__ = ["SignedRSIControlSnapshot", "VerifiedRSIControlProvider"]
