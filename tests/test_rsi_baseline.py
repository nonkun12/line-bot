import pytest

from core.rsi_baseline import FrozenBaseline, verify_frozen_baseline
from core.rsi_executor import RSIError


def make_baseline(*, quality=0.75, protocol="b" * 64, sealed_at=100):
    unsigned = FrozenBaseline(
        "baseline-2026-11", "a" * 64, protocol, quality, 100, sealed_at, "pending"
    )
    return FrozenBaseline(
        unsigned.baseline_id, unsigned.model_digest, unsigned.protocol_digest,
        unsigned.quality, unsigned.sample_count, unsigned.sealed_at,
        "signed:" + unsigned.digest,
    )


def verify(digest, signature):
    return signature == "signed:" + digest


def test_signed_frozen_baseline_verifies_and_returns_quality():
    baseline = make_baseline()
    assert verify_frozen_baseline(
        baseline, verify_signature=verify, expected_protocol_digest="b" * 64, now=200
    ) == 0.75


def test_baseline_rejects_wrong_protocol_and_invalid_signature():
    baseline = make_baseline()
    with pytest.raises(RSIError, match="protocol"):
        verify_frozen_baseline(
            baseline, verify_signature=verify, expected_protocol_digest="c" * 64, now=200
        )
    bad = FrozenBaseline(
        baseline.baseline_id, baseline.model_digest, baseline.protocol_digest,
        baseline.quality, baseline.sample_count, baseline.sealed_at, "forged"
    )
    with pytest.raises(RSIError, match="signature"):
        verify_frozen_baseline(
            bad, verify_signature=verify, expected_protocol_digest="b" * 64, now=200
        )


def test_baseline_rejects_bool_score_and_stale_snapshot():
    baseline = make_baseline(quality=True)
    with pytest.raises(RSIError, match="quality"):
        verify_frozen_baseline(
            baseline, verify_signature=verify, expected_protocol_digest="b" * 64, now=200
        )
    stale = make_baseline(sealed_at=1)
    with pytest.raises(RSIError, match="stale"):
        verify_frozen_baseline(
            stale, verify_signature=verify, expected_protocol_digest="b" * 64, now=40_000
        )
