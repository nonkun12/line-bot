from __future__ import annotations

import pytest

from core.idea_evidence import EvidenceVerification
from core.idea_evidence_store import RevisionConflict, SQLiteIdeaEvidenceStore
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_research_cycle import IdeaResearchCycle


def hypothesis():
    return ExperimentHypothesis(
        hypothesis_id="full-cycle-h1",
        statement="A smaller context improves response latency.",
        prediction="p95 latency falls to 80ms or lower.",
        metric="p95 latency ms",
        direction="decrease",
        baseline=100.0,
        success_threshold=80.0,
        failure_threshold=95.0,
        baseline_source="baseline artifact",
        measurement_method="fixed 100 request benchmark",
        evidence_requirements=("raw samples", "environment metadata"),
        reproducibility_steps=("run baseline", "run candidate"),
    )


def populated_cycle():
    cycle = IdeaResearchCycle.start("improve idea research", context=("local-only", "fail-closed"))
    cycle = cycle.register_hypothesis(hypothesis())
    cycle = cycle.record_observation(
        "full-cycle-h1",
        style=cycle.ideas[0].style,
        observed_value=75.0,
        source_ref="artifact://full-cycle/run-1",
        commit_sha="a" * 40,
        environment="linux-x86_64",
        sample_count=100,
        measured_at="2026-11-19T00:00:00Z",
        evidence_sha256="b" * 64,
    )
    cycle = cycle.attest_evidence(
        "full-cycle-h1",
        "b" * 64,
        EvidenceVerification(
            verifier="independent-review",
            verification_ref="review://full-cycle/1",
            verified_at="2026-11-19T00:01:00Z",
            checks=("commit and artifact digest inspected",),
        ),
    )
    return cycle


def test_cycle_json_round_trip_preserves_ideas_hypotheses_workflow_and_evidence():
    original = populated_cycle()
    restored = IdeaResearchCycle.from_json(original.to_json())

    assert restored.focus == original.focus
    assert restored.context == original.context
    assert restored.ideas == original.ideas
    assert restored.hypotheses == original.hypotheses
    assert restored.workflow == original.workflow
    assert restored.ledger == original.ledger
    assert restored.to_json() == original.to_json()


def test_cycle_json_rejects_unknown_versions_and_unregistered_evidence():
    payload = populated_cycle().to_json()
    with pytest.raises(ValueError, match="schema version"):
        IdeaResearchCycle.from_json(payload.replace('"schema_version":1', '"schema_version":2'))


def test_sqlite_store_round_trips_complete_cycle_and_revision_guards(tmp_path):
    store = SQLiteIdeaEvidenceStore(tmp_path / "complete-cycle.sqlite3")
    original = populated_cycle()

    assert store.load_cycle("cycle-a") is None
    assert store.save_cycle("cycle-a", original, expected_revision=0) == 1
    loaded = store.load_cycle("cycle-a")
    assert loaded is not None
    assert loaded.revision == 1
    assert loaded.cycle == original

    with pytest.raises(RevisionConflict):
        store.save_cycle("cycle-a", original, expected_revision=0)

    changed = original.register_hypothesis(
        ExperimentHypothesis(
            hypothesis_id="full-cycle-h2",
            statement="A second independent hypothesis.",
            prediction="throughput rises to 120.",
            metric="throughput",
            direction="increase",
            baseline=100.0,
            success_threshold=120.0,
            failure_threshold=90.0,
            baseline_source="throughput baseline",
            measurement_method="fixed load benchmark",
            evidence_requirements=("raw samples",),
            reproducibility_steps=("run fixed load",),
        )
    )
    assert store.save_cycle("cycle-a", changed, expected_revision=1) == 2
    assert store.load_cycle("cycle-a").cycle.hypotheses == changed.hypotheses


def test_cycle_restore_validates_ledger_references_and_schema_shape():
    original = populated_cycle()
    payload = original.to_json()
    malformed = payload.replace('"hypothesis_id":"full-cycle-h1"', '"hypothesis_id":"missing-hypothesis"', 1)
    with pytest.raises(ValueError):
        IdeaResearchCycle.from_json(malformed)
