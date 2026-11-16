import pytest

from core.rsi_control import SignedRSIControlSnapshot, VerifiedRSIControlProvider
from core.rsi_executor import EvidenceLedger, RSIError, canonical_digest


def make_snapshot(now, **overrides):
    data = {
        "global_hold": True,
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
    assert control.global_hold is True
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

    replay_ledger = EvidenceLedger(tmp_path / "replay.sqlite")
    first = make_snapshot(now, nonce="replay-nonce")
    second = make_snapshot(now, nonce="replay-nonce", global_hold=True)
    current = [first]
    provider = VerifiedRSIControlProvider(
        lambda: current[0], verify_signature=lambda *_: True,
        ledger=replay_ledger, clock=lambda: now,
    )
    provider()
    current[0] = second
    with pytest.raises(RSIError, match="reused"):
        provider()



def test_control_generation_is_monotonic_across_provider_restart(tmp_path):
    now = 2000
    ledger = EvidenceLedger(tmp_path / "generation.sqlite")
    first = make_snapshot(now, generation=1, nonce="gen-1")
    provider = VerifiedRSIControlProvider(
        lambda: first, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=ledger, clock=lambda: now,
    )
    provider()

    rollback = make_snapshot(now + 1, generation=0, nonce="gen-0")
    restarted = VerifiedRSIControlProvider(
        lambda: rollback, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=EvidenceLedger(tmp_path / "generation.sqlite"), clock=lambda: now + 1,
    )
    with pytest.raises(RSIError, match="generation rollback"):
        restarted()

    next_snapshot = make_snapshot(now + 2, generation=2, nonce="gen-2")
    next_provider = VerifiedRSIControlProvider(
        lambda: next_snapshot, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=EvidenceLedger(tmp_path / "generation.sqlite"), clock=lambda: now + 2,
    )
    assert next_provider().global_hold is False


def test_control_issued_at_rollback_is_rejected(tmp_path):
    now = 3000
    ledger = EvidenceLedger(tmp_path / "issued.sqlite")
    first = make_snapshot(now, generation=1, nonce="issued-1")
    VerifiedRSIControlProvider(
        lambda: first, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=ledger, clock=lambda: now,
    )()
    rollback = make_snapshot(now - 1, generation=2, nonce="issued-2")
    with pytest.raises(RSIError, match="issued_at rollback"):
        VerifiedRSIControlProvider(
            lambda: rollback, verify_signature=lambda d, s: s == "sig:" + d,
            ledger=ledger, clock=lambda: now,
        )()


def test_hold_release_requires_separate_signed_control_approval(tmp_path):
    from core.rsi_control import HumanControlReleaseApproval

    now = 4000
    ledger = EvidenceLedger(tmp_path / "release.sqlite")
    hold = make_snapshot(now, generation=1, nonce="hold-1", global_hold=True)
    VerifiedRSIControlProvider(
        lambda: hold, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=ledger, clock=lambda: now,
    )()

    release_snapshot = make_snapshot(now + 1, generation=2, nonce="release-snapshot")
    with pytest.raises(RSIError, match="separate human control approval"):
        VerifiedRSIControlProvider(
            lambda: release_snapshot, verify_signature=lambda d, s: s == "sig:" + d,
            ledger=ledger, clock=lambda: now + 1,
        )()

    signed_snapshot = {
        "global_hold": release_snapshot.global_hold,
        "execution_enabled": release_snapshot.execution_enabled,
        "free_only": release_snapshot.free_only,
        "budget_known": release_snapshot.budget_known,
        "budget_remaining_units": release_snapshot.budget_remaining_units,
        "paid_fallback_enabled": release_snapshot.paid_fallback_enabled,
        "issued_at": release_snapshot.issued_at,
        "expires_at": release_snapshot.expires_at,
        "nonce": release_snapshot.nonce,
        "generation": release_snapshot.generation,
    }
    snapshot_digest = canonical_digest(signed_snapshot)
    approval_fields = {
        "previous_hold_generation": 1,
        "release_generation": 2,
        "snapshot_digest": snapshot_digest,
        "snapshot_nonce": release_snapshot.nonce,
        "approver_id": "human-operator",
        "nonce": "release-approval-1",
        "issued_at": now + 1,
        "expires_at": now + 30,
    }
    approval_digest = canonical_digest(approval_fields)
    approval = HumanControlReleaseApproval(
        **approval_fields, signature="sig:" + approval_digest,
    )
    provider = VerifiedRSIControlProvider(
        lambda: release_snapshot,
        verify_signature=lambda d, s: s == "sig:" + d,
        verify_control_release=lambda d, s: s == "sig:" + d,
        release_approval_source=lambda: approval,
        ledger=ledger, clock=lambda: now + 1,
    )
    assert provider().global_hold is False
    assert ledger.verify()



def test_same_generation_with_altered_snapshot_is_rejected(tmp_path):
    now = 6000
    ledger = EvidenceLedger(tmp_path / "same-generation.sqlite")
    first = make_snapshot(now, generation=1, nonce="same-1")
    VerifiedRSIControlProvider(
        lambda: first, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=ledger, clock=lambda: now,
    )()
    altered = make_snapshot(now + 1, generation=1, nonce="same-1-alt", budget_remaining_units=1)
    with pytest.raises(RSIError, match="generation rollback"):
        VerifiedRSIControlProvider(
            lambda: altered, verify_signature=lambda d, s: s == "sig:" + d,
            ledger=EvidenceLedger(tmp_path / "same-generation.sqlite"), clock=lambda: now + 1,
        )()


def test_legacy_control_history_without_generation_fails_closed(tmp_path):
    now = 7000
    ledger = EvidenceLedger(tmp_path / "legacy.sqlite")
    ledger.append("legacy-control", "verified_control_snapshot", {
        "digest": "a" * 64, "issued_at": now,
    })
    snapshot = make_snapshot(now + 1, generation=1, nonce="new-control")
    with pytest.raises(RSIError, match="legacy control history"):
        VerifiedRSIControlProvider(
            lambda: snapshot, verify_signature=lambda d, s: s == "sig:" + d,
            ledger=ledger, clock=lambda: now + 1,
        )()


def test_concurrent_control_providers_cannot_accept_two_same_generation_values(tmp_path):
    import threading

    now = 8000
    path = tmp_path / "concurrent.sqlite"
    ledger = EvidenceLedger(path)
    initial = make_snapshot(now, generation=1, nonce="concurrent-1")
    VerifiedRSIControlProvider(
        lambda: initial, verify_signature=lambda d, s: s == "sig:" + d,
        ledger=ledger, clock=lambda: now,
    )()
    snapshots = [
        make_snapshot(now + 1, generation=2, nonce="concurrent-2-a", budget_remaining_units=4),
        make_snapshot(now + 1, generation=2, nonce="concurrent-2-b", budget_remaining_units=3),
    ]
    barrier = threading.Barrier(2)
    outcomes = []

    def accept(snapshot):
        provider = VerifiedRSIControlProvider(
            lambda: snapshot, verify_signature=lambda d, s: s == "sig:" + d,
            ledger=EvidenceLedger(path), clock=lambda: now + 1,
        )
        barrier.wait()
        try:
            provider()
            outcomes.append("accepted")
        except RSIError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=accept, args=(snapshot,)) for snapshot in snapshots]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 1
    assert ledger.verify()
