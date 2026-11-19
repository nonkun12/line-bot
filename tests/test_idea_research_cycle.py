from __future__ import annotations

import pytest

from core.idea_evidence import EvidenceVerification
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_research_cycle import IdeaResearchCycle


def hypothesis(**overrides):
    values = {
        "hypothesis_id": "cycle-cache-v1",
        "statement": "A bounded cache reduces p95 latency.",
        "prediction": "p95 reaches 80ms or lower.",
        "metric": "p95 latency ms",
        "direction": "decrease",
        "baseline": 100.0,
        "success_threshold": 80.0,
        "failure_threshold": 95.0,
        "baseline_source": "baseline artifact commit abc123",
        "measurement_method": "fixed 100-request benchmark",
        "evidence_requirements": ("raw samples", "environment metadata"),
        "reproducibility_steps": ("run baseline", "run candidate"),
    }
    values.update(overrides)
    return ExperimentHypothesis(**values)


def verification():
    return EvidenceVerification(
        verifier="independent-review",
        verification_ref="review://cycle/1",
        verified_at="2026-11-19T00:00:00Z",
        checks=("artifact digest and commit inspected",),
    )


def record(cycle, value=79.0, source="artifact://cycle/run-1", digest="a" * 64):
    return cycle.record_observation(
        "cycle-cache-v1",
        style="recombine",
        observed_value=value,
        source_ref=source,
        commit_sha="b" * 40,
        environment="linux-x86_64 fixed dataset",
        sample_count=100,
        measured_at="2026-11-19T00:00:00Z",
        evidence_sha256=digest,
    )


def test_full_cycle_links_ideas_hypotheses_evidence_and_next_learning():
    cycle = IdeaResearchCycle.start("improve research", context=("free/local-first",))
    assert len(cycle.ideas) == 5
    assert len(cycle.workflow) == 3

    cycle = cycle.register_hypothesis(hypothesis())
    cycle = record(cycle)
    assert cycle.ledger.learning_outcomes()[0].result == "unverified"

    cycle = cycle.attest_evidence("cycle-cache-v1", "a" * 64, verification())
    assert cycle.ledger.learning_outcomes()[0].result == "success"
    assert cycle.next_ideas()[0].style == "recombine"
    assert cycle.evidence_snapshot() == cycle.ledger.to_json()


def test_cycle_is_immutable_and_rejects_unknown_or_duplicate_hypotheses():
    cycle = IdeaResearchCycle.start("improve research")
    registered = cycle.register_hypothesis(hypothesis())
    assert cycle.hypotheses == ()
    with pytest.raises(ValueError):
        registered.register_hypothesis(hypothesis())
    with pytest.raises(ValueError):
        cycle.record_observation(
            "missing",
            style="recombine",
            observed_value=1.0,
            source_ref="artifact://missing",
            commit_sha="b" * 40,
            environment="fixed",
            sample_count=1,
            measured_at="2026-11-19T00:00:00Z",
            evidence_sha256="c" * 64,
        )


def test_cycle_keeps_ambiguous_results_unverified_and_refuses_attestation():
    cycle = IdeaResearchCycle.start("improve research").register_hypothesis(hypothesis())
    cycle = record(cycle, value=90.0, source="artifact://cycle/ambiguous", digest="d" * 64)
    assert cycle.ledger.records[0].result == "unverified"
    with pytest.raises(ValueError):
        cycle.attest_evidence("cycle-cache-v1", "d" * 64, verification())


def test_cycle_rejects_unrelated_style_and_duplicate_evidence():
    cycle = IdeaResearchCycle.start("improve research").register_hypothesis(hypothesis())
    with pytest.raises(ValueError):
        cycle.record_observation(
            "cycle-cache-v1",
            style="invented",
            observed_value=79.0,
            source_ref="artifact://cycle/run",
            commit_sha="b" * 40,
            environment="fixed",
            sample_count=10,
            measured_at="2026-11-19T00:00:00Z",
            evidence_sha256="e" * 64,
        )
    cycle = record(cycle)
    with pytest.raises(ValueError):
        record(cycle)
