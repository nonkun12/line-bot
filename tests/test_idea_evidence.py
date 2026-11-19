from __future__ import annotations

import pytest

from core.idea_evidence import (
    EvidenceVerification,
    ExperimentEvidence,
    ExperimentEvidenceLedger,
    evidence_digest,
)


def verification(**overrides):
    values = {
        "verifier": "independent-review",
        "verification_ref": "review://evidence/42",
        "verified_at": "2026-11-19T00:00:00Z",
        "checks": ("digest matches retained artifact", "environment and commit recorded"),
    }
    values.update(overrides)
    return EvidenceVerification(**values)


def evidence(**overrides):
    values = {
        "hypothesis_id": "latency-cache-v1",
        "style": "recombine",
        "result": "success",
        "observed_value": 76.5,
        "metric": "p95 latency in milliseconds",
        "source_ref": "artifact://runs/42/latency.json",
        "commit_sha": "a" * 40,
        "environment": "linux-x86_64; python 3.12; fixed dataset v1",
        "sample_count": 100,
        "measured_at": "2026-11-19T00:00:00Z",
        "evidence_sha256": "b" * 64,
        "note": "Repeated lookup benchmark",
        "verification": verification(),
    }
    values.update(overrides)
    return ExperimentEvidence(**values)


def test_verified_evidence_becomes_learning_signal():
    record = evidence()
    outcome = record.to_idea_outcome()
    assert record.is_verified
    assert outcome.result == "success"
    assert "review://evidence/42" in outcome.evidence


def test_unverified_result_never_becomes_success_signal():
    record = evidence(verification=None)
    assert not record.is_verified
    assert record.to_idea_outcome().result == "unverified"


def test_explicit_unverified_result_cannot_claim_attestation():
    with pytest.raises(ValueError):
        evidence(result="unverified")


@pytest.mark.parametrize(
    "overrides",
    [
        {"commit_sha": "not-a-sha"},
        {"evidence_sha256": "bad"},
        {"sample_count": 0},
        {"sample_count": True},
        {"measured_at": "2026-11-19T00:00:00"},
        {"observed_value": float("nan")},
        {"source_ref": ""},
        {"style": " "},
    ],
)
def test_rejects_incomplete_or_invalid_provenance(overrides):
    with pytest.raises(ValueError):
        evidence(**overrides)


def test_ledger_is_immutable_deduplicated_and_supplies_only_attested_learning():
    verified = evidence()
    unverified = evidence(
        hypothesis_id="other-hypothesis",
        source_ref="artifact://runs/43/latency.json",
        verification=None,
    )
    ledger = ExperimentEvidenceLedger().append(verified).append(unverified)
    assert len(ledger.records) == 2
    assert [item.result for item in ledger.learning_outcomes()] == ["success", "unverified"]
    with pytest.raises(ValueError):
        ledger.append(verified)
    assert len(ExperimentEvidenceLedger().records) == 0


def test_ledger_rejects_duplicate_records_at_construction():
    record = evidence()
    with pytest.raises(ValueError):
        ExperimentEvidenceLedger((record, record))


def test_digest_is_deterministic_and_requires_bytes():
    assert evidence_digest(b"same artifact") == evidence_digest(b"same artifact")
    assert evidence_digest(b"same artifact") != evidence_digest(b"different artifact")
    with pytest.raises(ValueError):
        evidence_digest(b"")
