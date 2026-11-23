from dataclasses import replace
import hashlib
import json

import pytest

from core.ai_factory_stage201_205_longitudinal_capability_trends import (
    CapabilityTrendError, Stage201CapabilitySnapshot, Stage202GenerationLineage,
    Stage203204TrendAnalyzer, Stage205RSITrendGate, verify_rsi_trend_certificate,
)

SIGN = lambda digest: "signed:" + digest
VERIFY = lambda digest, signature: signature == SIGN(digest)
H = "a" * 64
J = "b" * 64
K = "c" * 64


def snapshots(qualities=(.90, .91, .92), safeties=(.97, .97, .98),
              latencies=(100, 102, 104), memories=(500, 505, 510)):
    rows = []
    for i in range(3):
        rows.append(Stage201CapabilitySnapshot().build(
            snapshot_id=f"snap-{i}", candidate_id=f"candidate-{i}",
            artifact_digest=(hex(i + 10)[2:] * 64)[:64], generation=i,
            suite_digest=H, dataset_digest=J, environment_digest=K,
            provenance_certificate_digest="d" * 64, evaluator_id="independent-eval",
            quality=qualities[i], safety=safeties[i], latency_ms=latencies[i],
            memory_mb=memories[i], nonce=f"nonce-{i}", sign=SIGN, verify=VERIFY,
        ))
    return tuple(rows)


def pipeline(rows):
    lineage = Stage202GenerationLineage().build(
        rows, verify_snapshot_signature=VERIFY, sign=SIGN, verify=VERIFY,
    )
    trend = Stage203204TrendAnalyzer().build(
        rows, lineage, verify_lineage_signature=VERIFY, sign=SIGN, verify=VERIFY,
    )
    cert = Stage205RSITrendGate().build(
        trend, verify_trend_signature=VERIFY, sign=SIGN, verify=VERIFY,
    )
    return lineage, trend, cert


def test_supported_trend_requires_three_fixed_environment_generations():
    rows = snapshots()
    lineage, trend, cert = pipeline(rows)
    assert trend.supported is True
    assert cert.status == "CAPABILITY_TREND_SUPPORTED"
    assert verify_rsi_trend_certificate(cert, verify=VERIFY)
    assert cert.model_activation_authorized is False


def test_lineage_rejects_suite_dataset_or_environment_change():
    rows = list(snapshots())
    rows[2] = replace(rows[2], dataset_digest="e" * 64)
    with pytest.raises(CapabilityTrendError, match="must remain fixed"):
        Stage202GenerationLineage().build(
            rows, verify_snapshot_signature=VERIFY, sign=SIGN, verify=VERIFY,
        )


def test_lineage_rejects_generation_gap_and_duplicate_artifact():
    rows = list(snapshots())
    rows[2] = replace(rows[2], generation=4)
    with pytest.raises(CapabilityTrendError, match="consecutive"):
        Stage202GenerationLineage().build(
            rows, verify_snapshot_signature=VERIFY, sign=SIGN, verify=VERIFY,
        )
    rows = list(snapshots())
    rows[2] = replace(rows[2], artifact_digest=rows[1].artifact_digest)
    with pytest.raises(CapabilityTrendError, match="distinct artifact"):
        Stage202GenerationLineage().build(
            rows, verify_snapshot_signature=VERIFY, sign=SIGN, verify=VERIFY,
        )


def test_trend_blocks_safety_regression_even_when_quality_improves():
    _, trend, cert = pipeline(snapshots(safeties=(.98, .96, .97)))
    assert trend.supported is False
    assert cert.status == "INSUFFICIENT_OR_REGRESSING_EVIDENCE"


def test_trend_rejects_latency_or_memory_regression():
    _, trend, cert = pipeline(snapshots(latencies=(100, 110, 120)))
    assert trend.supported is False
    assert cert.status == "INSUFFICIENT_OR_REGRESSING_EVIDENCE"


def test_trend_rejects_tampered_snapshot():
    rows = list(snapshots())
    rows[1] = replace(rows[1], quality=.999)
    with pytest.raises(CapabilityTrendError, match="signature or digest invalid"):
        Stage202GenerationLineage().build(
            rows, verify_snapshot_signature=VERIFY, sign=SIGN, verify=VERIFY,
        )


def test_stage205_rejects_tampering_and_authority_escalation():
    _, _, cert = pipeline(snapshots())
    assert not verify_rsi_trend_certificate(replace(cert, sample_count=99), verify=VERIFY)
    assert not verify_rsi_trend_certificate(
        replace(cert, weight_mutation_authorized=True), verify=VERIFY,
    )


@pytest.mark.parametrize("stage", [201, 202, 203, 205])
def test_hold_fails_closed(stage):
    rows = snapshots()
    with pytest.raises(CapabilityTrendError, match="HOLD"):
        if stage == 201:
            Stage201CapabilitySnapshot().build(
                snapshot_id="blocked", candidate_id="c", artifact_digest=H,
                generation=0, suite_digest=H, dataset_digest=J, environment_digest=K,
                provenance_certificate_digest="d" * 64, evaluator_id="e",
                quality=.9, safety=.99, latency_ms=10, memory_mb=20, nonce="n",
                sign=SIGN, verify=VERIFY, hold_active=True,
            )
        elif stage == 202:
            Stage202GenerationLineage().build(
                rows, verify_snapshot_signature=VERIFY, sign=SIGN,
                verify=VERIFY, hold_active=True,
            )
        elif stage == 203:
            lineage = Stage202GenerationLineage().build(
                rows, verify_snapshot_signature=VERIFY, sign=SIGN, verify=VERIFY,
            )
            Stage203204TrendAnalyzer().build(
                rows, lineage, verify_lineage_signature=VERIFY, sign=SIGN,
                verify=VERIFY, hold_active=True,
            )
        else:
            _, trend, _ = pipeline(rows)
            Stage205RSITrendGate().build(
                trend, verify_trend_signature=VERIFY, sign=SIGN,
                verify=VERIFY, hold_active=True,
            )
