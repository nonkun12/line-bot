from __future__ import annotations

import pytest

from core.idea_evidence import ExperimentEvidence
from core.idea_evidence_store import ExperimentEvidenceStore
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_research_cycle import IdeaResearchCycle


@pytest.fixture
def hypothesis():
    return ExperimentHypothesis(
        hypothesis_id="cycle-hypothesis",
        statement="The new strategy improves throughput.",
        prediction="Throughput reaches at least 120 requests per second.",
        metric="requests per second",
        direction="increase",
        baseline=100.0,
        success_threshold=120.0,
        failure_threshold=105.0,
        baseline_source="Fixed baseline run baseline-01.",
        measurement_method="Same machine and workload for each run.",
        evidence_requirements=("raw throughput samples",),
        reproducibility_steps=("run fixed workload",),
    )


def evidence(experiment_id, style, measured_value, status="verified", reviewer="review-1"):
    return ExperimentEvidence(
        experiment_id=experiment_id,
        hypothesis_id="cycle-hypothesis",
        style=style,
        measured_value=measured_value,
        evidence_refs=(f"artifact:{experiment_id}",),
        code_revision="a" * 40,
        environment="linux; python=3.x",
        verification_status=status,
        verified_by=reviewer if status == "verified" else "",
    )


def test_cycle_connects_plan_persistence_and_next_ideation(tmp_path, hypothesis):
    store = ExperimentEvidenceStore(tmp_path / "cycle.sqlite3")
    cycle = IdeaResearchCycle(store)

    batches = cycle.plan("improve autonomous reasoning")
    assert len(batches) == 3

    for i in range(20):
        cycle.record_evidence(evidence(f"good-{i}", "recombine", 125.0))
        cycle.record_evidence(evidence(f"bad-{i}", "reframe", 102.0))

    ideas = cycle.propose_next("improve autonomous reasoning", hypothesis)
    styles = [idea.style for idea in ideas]
    assert styles.index("recombine") < styles.index("reframe")
    assert all("No implementation, execution, merge, deploy" in idea.task.instruction for idea in ideas)


def test_cycle_keeps_pending_results_out_of_learning(tmp_path, hypothesis):
    cycle = IdeaResearchCycle(ExperimentEvidenceStore(tmp_path / "cycle.sqlite3"))
    cycle.record_evidence(evidence("pending-1", "recombine", 125.0, status="pending"))
    baseline = cycle.propose_next("improve autonomous reasoning", hypothesis)
    assert baseline[0].style == "reframe"


def test_cycle_rejects_invalid_context_and_hypothesis(tmp_path):
    cycle = IdeaResearchCycle(ExperimentEvidenceStore(tmp_path / "cycle.sqlite3"))
    with pytest.raises(ValueError):
        cycle.propose_next("focus", None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        cycle.propose_next(
            "focus",
            ExperimentHypothesis(
                hypothesis_id="h",
                statement="s",
                prediction="p",
                metric="m",
                direction="increase",
                baseline=1.0,
                success_threshold=3.0,
                failure_threshold=2.0,
                baseline_source="source",
                measurement_method="method",
                evidence_requirements=("evidence",),
                reproducibility_steps=("step",),
            ),
            context=tuple(f"ctx-{i}" for i in range(9)),
        )
