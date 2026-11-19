from __future__ import annotations

import pytest

from core.idea_evidence import EvidenceVerification
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_research_cycle import IdeaResearchCycle
from core.idea_research_cycle_store import (
    CycleRevisionConflict,
    SQLiteIdeaResearchCycleStore,
)


def hypothesis():
    return ExperimentHypothesis(
        hypothesis_id="restore-h1",
        statement="A bounded cache reduces latency.",
        prediction="p95 is at most 80ms.",
        metric="p95 latency ms",
        direction="decrease",
        baseline=100.0,
        success_threshold=80.0,
        failure_threshold=95.0,
        baseline_source="baseline artifact",
        measurement_method="fixed benchmark",
        evidence_requirements=("raw samples",),
        reproducibility_steps=("run baseline", "run candidate"),
    )


def cycle_with_evidence():
    cycle = IdeaResearchCycle.start("improve local research", context=("free-first",))
    cycle = cycle.register_hypothesis(hypothesis())
    cycle = cycle.record_observation(
        "restore-h1",
        style=cycle.ideas[0].style,
        observed_value=79.0,
        source_ref="artifact://restore/run-1",
        commit_sha="a" * 40,
        environment="local reproducible test",
        sample_count=50,
        measured_at="2026-11-19T00:00:00Z",
        evidence_sha256="b" * 64,
    )
    cycle = cycle.attest_evidence(
        "restore-h1",
        "b" * 64,
        EvidenceVerification(
            verifier="independent-review",
            verification_ref="review://restore/1",
            verified_at="2026-11-19T00:01:00Z",
            checks=("digest and source inspected",),
        ),
    )
    return cycle


def test_complete_cycle_round_trip_restores_all_state_and_learning(tmp_path):
    store = SQLiteIdeaResearchCycleStore(tmp_path / "state" / "cycle.sqlite3")
    original = cycle_with_evidence()
    assert store.save("idea-ai", original, expected_revision=0) == 1

    snapshot = store.load("idea-ai")
    assert snapshot is not None
    assert snapshot.revision == 1
    restored = snapshot.cycle
    assert restored.focus == original.focus
    assert restored.context == original.context
    assert restored.ideas == original.ideas
    assert restored.workflow == original.workflow
    assert restored.hypotheses == original.hypotheses
    assert restored.ledger == original.ledger
    assert restored.next_ideas() == original.next_ideas()


def test_cycle_store_uses_optimistic_revision_and_preserves_old_state(tmp_path):
    store = SQLiteIdeaResearchCycleStore(tmp_path / "cycle.sqlite3")
    original = cycle_with_evidence()
    store.save("idea-ai", original, expected_revision=0)
    with pytest.raises(CycleRevisionConflict):
        store.save("idea-ai", IdeaResearchCycle.start("overwrite"), expected_revision=0)
    assert store.load("idea-ai").cycle == original


def test_cycle_store_handles_missing_namespace_and_validates_inputs(tmp_path):
    store = SQLiteIdeaResearchCycleStore(tmp_path / "cycle.sqlite3")
    assert store.load("missing") is None
    with pytest.raises(ValueError):
        store.save(" ", cycle_with_evidence(), expected_revision=0)
    with pytest.raises(ValueError):
        store.save("idea-ai", cycle_with_evidence(), expected_revision=-1)
    with pytest.raises(TypeError):
        store.save("idea-ai", object(), expected_revision=0)


def test_cycle_store_rejects_memory_database_and_directory(tmp_path):
    with pytest.raises(ValueError):
        SQLiteIdeaResearchCycleStore(":memory:")
    with pytest.raises(ValueError):
        SQLiteIdeaResearchCycleStore(tmp_path)


def test_cycle_store_database_file_is_private(tmp_path):
    path = tmp_path / "cycle.sqlite3"
    store = SQLiteIdeaResearchCycleStore(path)
    store.save("idea-ai", cycle_with_evidence(), expected_revision=0)
    assert path.stat().st_mode & 0o077 == 0
