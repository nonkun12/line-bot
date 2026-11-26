import pytest

from core.rsi_control import SignedRSIControlSnapshot
from core.rsi_orca_auth import (
    OrcaRSIControlSource,
    RSIControlTransportError,
    make_signed_envelope,
    parse_signed_envelope,
)


SECRET = "test-only-dedicated-rsi-control-secret-32"


def _snapshot(**changes):
    values = dict(
        global_hold=True,
        execution_enabled=False,
        free_only=True,
        budget_known=False,
        budget_remaining_units=0,
        paid_fallback_enabled=False,
        issued_at=100,
        expires_at=160,
        nonce="orca-test-0001",
        generation=1,
        signature="ignored-input-signature",
    )
    values.update(changes)
    return SignedRSIControlSnapshot(**values)


def test_signed_orca_control_envelope_round_trips():
    snapshot = _snapshot()
    envelope = make_signed_envelope(snapshot, SECRET)
    parsed = parse_signed_envelope(envelope, SECRET)

    assert parsed.global_hold is True
    assert parsed.execution_enabled is False
    assert parsed.generation == 1
    assert parsed.signature == envelope["signature"]


def test_tampered_snapshot_is_rejected():
    envelope = make_signed_envelope(_snapshot(), SECRET)
    envelope["payload"]["execution_enabled"] = True

    with pytest.raises(RSIControlTransportError, match="signature"):
        parse_signed_envelope(envelope, SECRET)


def test_missing_or_short_secret_fails_closed():
    with pytest.raises(RSIControlTransportError, match="secret"):
        make_signed_envelope(_snapshot(), "short")


def test_unknown_fields_are_rejected():
    envelope = make_signed_envelope(_snapshot(), SECRET)
    envelope["payload"]["allow_merge"] = True

    with pytest.raises(RSIControlTransportError, match="schema"):
        parse_signed_envelope(envelope, SECRET)


def test_control_source_fetches_and_verifies_before_returning():
    envelope = make_signed_envelope(_snapshot(), SECRET)
    source = OrcaRSIControlSource(lambda: envelope, lambda: SECRET)

    assert source().global_hold is True


def test_control_source_fails_closed_when_transport_unavailable():
    source = OrcaRSIControlSource(lambda: (_ for _ in ()).throw(OSError("offline")), lambda: SECRET)

    with pytest.raises(RSIControlTransportError, match="unavailable"):
        source()
