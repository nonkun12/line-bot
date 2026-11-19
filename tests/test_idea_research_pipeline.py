from __future__ import annotations

import pytest

from core.idea_evidence import ExperimentEvidence
from core.idea_hypothesis import ExperimentHypothesis
from core.idea_research_pipeline import build_idea_research_plan
from core.multi_agent import AgentRole


SHA = "b" * 40


@pytest.fixture
def hypothesis():
    return ExperimentHypothesis(
        hypothesis_id="quality-v1",
        statement="A critique stage improves idea quality.",
        prediction="The quality score increases.",
        metric="review quality score",
        direction="increase",
        baseline=50.0,
        success_threshold=80.0,
        failure_threshold=60.0,
        baseline_source="baseline-review.json",
        measurement_method="same rubric and independent reviewers",
        evidence_requirements=("review records",),
        reproducibility_steps=("run fixed rubric",),
    )


def evidence(**overrides):
    values = {
        "experiment_id": "exp-001",
        "hypothesis_id": "quality-v1",
        "style": "recombine",
        "measured_value": 90.0,
        "evidence_refs": ("artifact:sha256:quality",),
        "code_revision": SHA,
        "environment": "python=3.x; runner=linux",
        "verification_status": "verified",
        "verified_by": "independent-review",
    }
    values.update(overrides)
    return ExperimentEvidence(**values)


def test_builds_full_ideation_review_synthesis_cycle(hypothesis):
    plan = build_idea_research_plan(
        "improve self-directed research",
        context=("free/local-first", "fail closed"),
        hypothesis=hypothesis,
        evidence_records=(evidence(),),
    )
    assert len(plan.idea_candidates) == 5
    assert len(plan.workflow_batches) == 3
    assert plan.workflow_batches[0].tasks[0].role is AgentRole.IDEA
    assert plan.workflow_batches[1].tasks[0].role is AgentRole.REVIEWER
    assert plan.workflow_batches[2].tasks[0].role is AgentRole.INTEGRATOR
    assert plan.verified_count == 1
    assert plan.unverified_count == 0
    assert plan.learning_outcomes[0].result == "success"
    assert "recombine" in {idea.style for idea in plan.idea_candidates}


def test_unverified_evidence_never_changes_learning_selection(hypothesis):
    baseline = build_idea_research_plan("improve reasoning")
    plan = build_idea_research_plan(
        "improve reasoning",
        hypothesis=hypothesis,
        evidence_records=(evidence(verification_status="pending", verified_by=""),),
    )
    assert tuple(i.style for i in plan.idea_candidates) == tuple(
        i.style for i in baseline.idea_candidates
    )
    assert plan.verified_count == 0
    assert plan.unverified_count == 1


def test_rejects_evidence_without_hypothesis():
    with pytest.raises(ValueError, match="hypothesis is required"):
        build_idea_research_plan("focus", evidence_records=(evidence(),))


def test_rejects_excessive_evidence_records(hypothesis):
    with pytest.raises(ValueError, match="exceeds"):
        build_idea_research_plan(
            "focus",
            hypothesis=hypothesis,
            evidence_records=(evidence(),) * 501,
        )


def test_cycle_is_plan_only_and_does_not_grant_execution():
    plan = build_idea_research_plan("improve safe autonomy")
    all_tasks = [
        task
        for batch in plan.workflow_batches
        for task in batch.tasks
    ] + [idea.task for idea in plan.idea_candidates]
    assert all(
        "execute" in task.instruction.lower()
        or "execution" in task.instruction.lower()
        or "実行" in task.instruction
        for task in all_tasks
    )
    assert all("merge" in task.instruction.lower() for task in all_tasks)
    assert all("deploy" in task.instruction.lower() for task in all_tasks)
    assert not hasattr(plan, "execute")
    assert not hasattr(plan, "approval_granted")



def test_builds_next_plan_directly_from_persisted_evidence(tmp_path, hypothesis):
    from core.idea_evidence_store import append_evidence_record
    from core.idea_research_pipeline import build_idea_research_plan_from_store

    path = tmp_path / "idea-evidence.jsonl"
    append_evidence_record(path, evidence())
    plan = build_idea_research_plan_from_store(
        "improve self-directed research",
        hypothesis=hypothesis,
        evidence_store_path=path,
    )
    assert plan.verified_count == 1
    assert plan.learning_outcomes[0].result == "success"
    assert len(plan.workflow_batches) == 3
    assert len(plan.idea_candidates) == 5
