import pytest

from core.rsi_control import SignedRSIControlSnapshot, VerifiedRSIControlProvider
from core.rsi_executor import EvidenceLedger, RSIError, canonical_digest


def make_snapshot(now, **overrides):
    data = {
        "global_hold": False,
        "execution_enabled": False,
        "free_only": True,
        "budget_known": True,
        "budget_remaining_units": 5,
        "paid_fallback_enabled": False,
        "issued_at": now,
        "expires_at": now + 60,
        "nonce": "control-nonce-1",
        "generation": 1,
    }
    data.update(overrides)
    digest = canonical_digest(data)
    return SignedRSIControlSnapshot(**data, signature="sig:" + digest)


def test_verified_control_provider_accepts_signed_fresh_free_snapshot(tmp_path):
    now = 1000
    snapshot = make_snapshot(now)
    ledger = EvidenceLedger(tmp_path / "control.sqlite")
    provider = VerifiedRSIControlProvider(
        lambda: snapshot,
        verify_signature=lambda digest, signature: signature == "sig:" + digest,
        ledger=ledger,
        clock=lambda: now,
    )
    control = provider()
    assert control.global_hold is False
    assert control.free_only is True
    assert control.budget_known is True
    assert control.budget_remaining_units == 5
    assert provider() == control  # same fresh snapshot is safe within this provider
    assert ledger.verify()


def test_provider_fails_closed_on_invalid_signature_or_stale_snapshot(tmp_path):
    now = 1000
    ledger = EvidenceLedger(tmp_path / "control.sqlite")
    snapshot = make_snapshot(now)
    provider = VerifiedRSIControlProvider(
        lambda: snapshot, verify_signature=lambda *_: False,
        ledger=ledger, clock=lambda: now,
    )
    with pytest.raises(RSIError, match="signature"):
        provider()
    stale = make_snapshot(now - 500, nonce="old-nonce")
    provider = VerifiedRSIControlProvider(
        lambda: stale, verify_signature=lambda *_: True,
        ledger=ledger, clock=lambda: now,
    )
    with pytest.raises(RSIError, match="stale"):
        provider()


def test_provider_fails_closed_on_unknown_budget_and_replayed_nonce(tmp_path):
    now = 1000
    ledger = EvidenceLedger(tmp_path / "control.sqlite")
    unknown = make_snapshot(now, budget_known=False, budget_remaining_units=0)
    provider = VerifiedRSIControlProvider(
        lambda: unknown, verify_signature=lambda *_: True,
        ledger=ledger, clock=lambda: now,
    )
    assert provider().budget_known is False

    first = make_snapshot(now, nonce="replay-nonce")
    second = make_snapshot(now, nonce="replay-nonce", global_hold=True)
    current = [first]
    provider = VerifiedRSIControlProvider(
        lambda: current[0], verify_signature=lambda *_: True,
        ledger=ledger, clock=lambda: now,
    )
    provider()
    current[0] = second
    with pytest.raises(RSIError, match="reused"):
        provider()
