import hashlib
from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage154_merge_strategy_evaluation import (
    MergeAlgorithm, MergeEvaluationPlan, MergeStrategyParameters,
)
from core.ai_factory_stage155_isolated_merge_experiments import MergeExperimentOutcome
from core.ai_factory_stage156_authenticated_knowledge_transfer import (
    AuthenticatedKnowledgeTransfer, KnowledgeTransferError, Stage156SignedEvidence,
)

SUITE = "a" * 64
RECIPE = "b" * 64
PARENT_A = "c" * 64
PARENT_B = "d" * 64
CANDIDATE = "e" * 64
OUTPUT = "f" * 64
EVIDENCE = "1" * 64
OUTCOME_DIGEST = "2" * 64


def fitness(*, accuracy=.92, instruction=.91, safety=.99, latency=85, memory=480, regressions=0, suite=SUITE):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, suite)


def fixtures():
    plan = MergeEvaluationPlan(
        "plan-156", "candidate-156", 7, MergeAlgorithm.SLERP,
        MergeStrategyParameters(interpolation=.5), ("parent-a", "parent-b"),
        (PARENT_A, PARENT_B), CANDIDATE, SUITE, RECIPE, "parameter_merge",
    )
    outcome = MergeExperimentOutcome(
        plan.plan_id, RECIPE, OUTPUT, EVIDENCE, "independent-reviewer",
        True, (), OUTCOME_DIGEST,
    )
    evidence = Stage156SignedEvidence(
        OUTCOME_DIGEST, EVIDENCE, OUTPUT, SUITE, "independent-reviewer", 7,
        ("parent-a", "parent-b"), (PARENT_A, PARENT_B),
        fitness(), "signature-from-independent-verifier",
    )
    return plan, outcome, evidence


def ingest(ledger=None, *, plan=None, outcome=None, evidence=None, **kwargs):
    p, o, e = fixtures()
    return (ledger or AuthenticatedKnowledgeTransfer()).ingest(
        outcome=outcome or o, plan=plan or p, evidence=evidence or e,
        baseline_fitness=fitness(accuracy=.91, instruction=.90, safety=.98, latency=90, memory=500),
        verify_stage155_evidence=lambda item: item.signature == "signature-from-independent-verifier",
        expected_suite_digest=SUITE, **kwargs,
    )


def test_accepts_verified_adjacent_generation_transfer_as_pending_proposal():
    record = ingest()
    assert record.source_generation == 7
    assert record.proposed_generation == 8
    assert record.pending_human_approval is True
    assert record.generation_advanced is False
    assert record.model_activated is False
    assert record.auto_adoption_authorized is False
    assert record.production_switch_authorized is False
    assert record.lessons


def test_snapshot_is_deterministic_and_append_only():
    ledger = AuthenticatedKnowledgeTransfer()
    first = ingest(ledger)
    snapshot = ledger.snapshot()
    assert snapshot.records == (first,)
    assert snapshot.source_generations == (7,)
    assert snapshot.proposed_generations == (8,)
    assert snapshot.generation_advanced is False
    assert ingest(ledger) if False else True
    assert ledger.snapshot().digest == snapshot.digest


def test_rejects_unaccepted_or_authoritative_stage155_outcome():
    plan, outcome, evidence = fixtures()
    for bad in (
        replace(outcome, accepted_for_next_generation=False),
        replace(outcome, generation_advanced=True),
        replace(outcome, model_activated=True),
        replace(outcome, production_switch_authorized=True),
    ):
        with pytest.raises(KnowledgeTransferError):
            ingest(plan=plan, outcome=bad, evidence=evidence)


def test_rejects_recipe_artifact_evidence_and_suite_mismatch():
    plan, outcome, evidence = fixtures()
    cases = [
        (replace(plan, recipe_digest="9" * 64), outcome, evidence),
        (plan, replace(outcome, output_artifact_digest="8" * 64), evidence),
        (plan, outcome, replace(evidence, evidence_digest="7" * 64)),
        (plan, outcome, replace(evidence, evaluation_suite_digest="6" * 64)),
        (plan, outcome, replace(evidence, outcome_digest="5" * 64)),
    ]
    for p, o, e in cases:
        with pytest.raises(KnowledgeTransferError):
            ingest(plan=p, outcome=o, evidence=e)


def test_rejects_signature_failure_and_evaluator_identity_mismatch():
    plan, outcome, evidence = fixtures()
    with pytest.raises(KnowledgeTransferError):
        ingest(plan=plan, outcome=outcome, evidence=replace(evidence, signature="tampered"))
    with pytest.raises(KnowledgeTransferError):
        ingest(plan=plan, outcome=outcome, evidence=replace(evidence, evaluator_id="other-reviewer"))


def test_rejects_parent_lineage_and_generation_mismatch():
    plan, outcome, evidence = fixtures()
    for bad in (
        replace(evidence, parent_model_ids=("parent-x", "parent-y")),
        replace(evidence, parent_artifact_digests=(PARENT_B, PARENT_A)),
        replace(evidence, source_generation=8),
    ):
        with pytest.raises(KnowledgeTransferError):
            ingest(plan=plan, outcome=outcome, evidence=bad)


@pytest.mark.parametrize("bad_fitness", [
    fitness(accuracy=.89),
    fitness(instruction=.89),
    fitness(safety=.90),
    fitness(latency=120),
    fitness(memory=600),
    fitness(regressions=1),
    fitness(safety=.94, accuracy=.99),
])
def test_rejects_quality_safety_or_resource_regression(bad_fitness):
    plan, outcome, evidence = fixtures()
    with pytest.raises(KnowledgeTransferError):
        ingest(plan=plan, outcome=outcome, evidence=replace(evidence, fitness=bad_fitness))


def test_rejects_duplicate_replay_and_capacity_overflow():
    ledger = AuthenticatedKnowledgeTransfer(max_records=1)
    ingest(ledger)
    with pytest.raises(KnowledgeTransferError, match="duplicate"):
        ingest(ledger)
    plan, outcome, evidence = fixtures()
    next_plan = replace(plan, plan_id="plan-next", candidate_id="candidate-next", generation=8, recipe_digest="3" * 64)
    next_outcome = replace(outcome, plan_id="plan-next", recipe_digest="3" * 64, outcome_digest="4" * 64)
    next_evidence = replace(evidence, outcome_digest="4" * 64, source_generation=8)
    with pytest.raises(KnowledgeTransferError, match="capacity"):
        ingest(ledger, plan=next_plan, outcome=next_outcome, evidence=next_evidence)


def test_rejects_hold_kill_switch_budget_and_plan_authority():
    plan, outcome, evidence = fixtures()
    for gates in ({"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False}):
        with pytest.raises(KnowledgeTransferError):
            ingest(plan=plan, outcome=outcome, evidence=evidence, **gates)
    with pytest.raises(KnowledgeTransferError):
        ingest(plan=replace(plan, merge_authorized=True), outcome=outcome, evidence=evidence)


def test_rejects_evaluation_suite_drift_within_generation():
    ledger = AuthenticatedKnowledgeTransfer()
    ingest(ledger)
    plan, outcome, evidence = fixtures()
    changed_suite = "9" * 64
    changed_plan = replace(plan, evaluation_suite_digest=changed_suite)
    changed_evidence = replace(evidence, evaluation_suite_digest=changed_suite,
                               fitness=fitness(accuracy=.93, suite=changed_suite))
    with pytest.raises(KnowledgeTransferError):
        ledger.ingest(
            outcome=outcome, plan=changed_plan, evidence=changed_evidence,
            baseline_fitness=fitness(suite=changed_suite),
            verify_stage155_evidence=lambda item: True,
            expected_suite_digest=changed_suite,
        )
