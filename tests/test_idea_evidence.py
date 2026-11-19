from __future__ import annotations

import pytest

from core.idea_evidence import (
    EvidenceVerification,
    ExperimentEvidence,
    ExperimentEvidenceLedger,
    evidence_digest,
)
from core.idea_hypothesis import ExperimentHypothesis


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



def test_observation_factory_uses_hypothesis_thresholds_and_starts_unverified():
    hypothesis = ExperimentHypothesis(
        hypothesis_id="latency-v1",
        statement="Cache reduces p95 latency",
        prediction="p95 reaches 80ms or lower",
        metric="p95 latency ms",
        direction="decrease",
        baseline=100.0,
        success_threshold=80.0,
        failure_threshold=95.0,
        baseline_source="baseline artifact and commit",
        measurement_method="fixed 100-request benchmark",
        evidence_requirements=("raw samples",),
        reproducibility_steps=("run benchmark",),
    )
    record = ExperimentEvidence.from_observation(
        hypothesis,
        style="recombine",
        observed_value=79.0,
        source_ref="artifact://run/1",
        commit_sha="c" * 40,
        environment="linux-x86_64",
        sample_count=100,
        measured_at="2026-11-19T00:00:00Z",
        evidence_sha256="d" * 64,
    )
    assert record.result == "success"
    assert record.verification is None
    assert record.to_idea_outcome().result == "unverified"


def test_observation_factory_rejects_mismatched_hypothesis_type():
    with pytest.raises(TypeError):
        ExperimentEvidence.from_observation(
            object(),
            style="recombine",
            observed_value=1.0,
            source_ref="artifact://run/1",
            commit_sha="c" * 40,
            environment="linux-x86_64",
            sample_count=1,
            measured_at="2026-11-19T00:00:00Z",
            evidence_sha256="d" * 64,
        )



def test_ledger_json_round_trip_preserves_provenance_and_learning_gate():
    ledger = ExperimentEvidenceLedger().append(evidence()).append(
        evidence(
            hypothesis_id="unverified-hypothesis",
            source_ref="artifact://runs/99/latency.json",
            verification=None,
        )
    )
    encoded = ledger.to_json()
    restored = ExperimentEvidenceLedger.from_json(encoded)
    assert restored == ledger
    assert [outcome.result for outcome in restored.learning_outcomes()] == [
        "success",
        "unverified",
    ]
    assert restored.to_json() == encoded


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        '{"schema_version":2,"records":[]}',
        '{"schema_version":1,"records":[],"extra":true}',
        '{"schema_version":1,"records":[{}]}',
        '{"schema_version":1,"records":null}',
    ],
)
def test_ledger_json_loader_rejects_invalid_or_unknown_schemas(payload):
    with pytest.raises(ValueError):
        ExperimentEvidenceLedger.from_json(payload)


def test_ledger_json_loader_enforces_payload_size():
    with pytest.raises(ValueError):
        ExperimentEvidenceLedger.from_json(" " * 1_000_001)
