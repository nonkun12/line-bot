from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage156_authenticated_knowledge_transfer import GenerationKnowledge
from core.ai_factory_stage157_recursive_evolution_evaluation import (
    EvolutionVerdict, RecursiveEvaluationError, RecursiveEvolutionEvaluator,
    SignedGenerationEvaluation,
)

SUITE = "a" * 64
ARTIFACT_8 = "b" * 64
ARTIFACT_9 = "c" * 64
TRANSFER_8 = "d" * 64
TRANSFER_9 = "e" * 64
RECORD_8 = "f" * 64
RECORD_9 = "1" * 64


def fitness(accuracy=.90, instruction=.90, safety=.99, latency=100, memory=500, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


def transfer(generation=8):
    return GenerationKnowledge(
        transfer_id=TRANSFER_8 if generation == 8 else TRANSFER_9,
        source_generation=generation - 1, proposed_generation=generation,
        source_candidate_id=f"candidate-{generation}", parent_model_ids=("p1", "p2"),
        parent_artifact_digests=("2" * 64, "3" * 64),
        candidate_artifact_digest=ARTIFACT_8 if generation == 8 else ARTIFACT_9,
        evaluation_suite_digest=SUITE, recipe_digest="4" * 64, strategy="parameter_merge",
        fitness=fitness(), outcome_digest="5" * 64, evidence_digest="6" * 64,
        evaluator_id="stage156-evaluator", lessons=("lesson",),
        record_digest=RECORD_8 if generation == 8 else RECORD_9,
    )


def observation(generation=8, *, evaluator=None, metrics=None):
    return SignedGenerationEvaluation(
        generation=generation,
        transfer_id=TRANSFER_8 if generation == 8 else TRANSFER_9,
        transfer_record_digest=RECORD_8 if generation == 8 else RECORD_9,
        artifact_digest=ARTIFACT_8 if generation == 8 else ARTIFACT_9,
        evaluation_suite_digest=SUITE,
        evaluator_id=evaluator or f"independent-evaluator-{generation}",
        evidence_digest=(format(generation, "064x")) ,
        fitness=metrics or fitness(),
        signature="valid-signed-evidence",
    )


def add(evaluator, generation, metrics=None, *, verifier=None):
    item = observation(generation, metrics=metrics)
    return evaluator.ingest(
        transfer=transfer(generation), observation=item,
        verify_evaluation=verifier or (lambda evidence: evidence.signature == "valid-signed-evidence"),
    )


def test_first_generation_is_recorded_without_fabricated_trend():
    ledger = RecursiveEvolutionEvaluator()
    assert add(ledger, 8) is None
    snapshot = ledger.snapshot()
    assert snapshot.generations == (8,)
    assert snapshot.verdicts == ()
    assert snapshot.generation_advanced is False
    assert snapshot.model_activated is False


def test_improvement_generates_recursive_next_step_recommendation():
    ledger = RecursiveEvolutionEvaluator()
    add(ledger, 8, fitness())
    recommendation = add(ledger, 9, fitness(.92, .92, .995, 95, 480))
    assert recommendation.verdict == EvolutionVerdict.IMPROVED
    assert recommendation.after_generation == 9
    assert recommendation.proposal_only is True
    assert recommendation.execution_authorized is False
    assert recommendation.model_mutation_authorized is False
    assert recommendation.auto_adoption_authorized is False
    assert "isolated sandbox" in " ".join(recommendation.actions)


def test_stagnation_and_regression_are_distinguished():
    stagnant = RecursiveEvolutionEvaluator()
    add(stagnant, 8, fitness())
    assert add(stagnant, 9, fitness(.901, .901, .99, 100.5, 501)).verdict == EvolutionVerdict.STAGNANT

    regressed = RecursiveEvolutionEvaluator()
    add(regressed, 8, fitness())
    result = add(regressed, 9, fitness(.88, .90, .99, 100, 500))
    assert result.verdict == EvolutionVerdict.REGRESSED
    assert "block inheritance" in " ".join(result.actions)


def test_mixed_tradeoff_requires_human_review():
    ledger = RecursiveEvolutionEvaluator()
    add(ledger, 8, fitness())
    result = add(ledger, 9, fitness(.92, .90, .99, 108, 500))
    assert result.verdict == EvolutionVerdict.MIXED
    assert "human review" in " ".join(result.rationale)


def test_rejects_tampered_signature_and_transfer_binding():
    ledger = RecursiveEvolutionEvaluator()
    bad = replace(observation(8), signature="tampered")
    with pytest.raises(RecursiveEvaluationError):
        ledger.ingest(transfer=transfer(8), observation=bad, verify_evaluation=lambda _: False)

    bad_transfer = replace(transfer(8), candidate_artifact_digest="9" * 64)
    with pytest.raises(RecursiveEvaluationError):
        ledger.ingest(transfer=bad_transfer, observation=observation(8), verify_evaluation=lambda _: True)


def test_rejects_suite_drift_duplicate_and_non_adjacent_generation():
    ledger = RecursiveEvolutionEvaluator()
    add(ledger, 8)
    with pytest.raises(RecursiveEvaluationError, match="suite drift"):
        ledger.ingest(
            transfer=replace(transfer(9), evaluation_suite_digest="9" * 64),
            observation=replace(observation(9), evaluation_suite_digest="9" * 64,
                                fitness=Fitness(.92, .92, .99, 95, 480, 0, "9" * 64)),
            verify_evaluation=lambda _: True,
        )
    with pytest.raises(RecursiveEvaluationError, match="adjacent"):
        ledger.ingest(transfer=transfer(10), observation=observation(10),
                      verify_evaluation=lambda _: True)
    with pytest.raises(RecursiveEvaluationError, match="duplicate"):
        ledger.ingest(transfer=transfer(8), observation=observation(8),
                      verify_evaluation=lambda _: True)


def test_requires_distinct_evaluators_and_blocks_hold_kill_switch_budget():
    ledger = RecursiveEvolutionEvaluator()
    add(ledger, 8)
    same = replace(observation(9), evaluator_id="independent-evaluator-8")
    with pytest.raises(RecursiveEvaluationError, match="independent evaluator"):
        ledger.ingest(transfer=transfer(9), observation=same, verify_evaluation=lambda _: True)
    for flags in ({"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False}):
        with pytest.raises(RecursiveEvaluationError):
            ledger.ingest(transfer=transfer(9), observation=observation(9),
                          verify_evaluation=lambda _: True, **flags)


def test_rejects_safety_floor_and_evaluation_regressions():
    for metrics in (fitness(safety=.94, accuracy=.99), fitness(regressions=1)):
        ledger = RecursiveEvolutionEvaluator()
        with pytest.raises(RecursiveEvaluationError):
            add(ledger, 8, metrics)


def test_snapshot_digest_is_stable_and_streaks_are_reported():
    ledger = RecursiveEvolutionEvaluator()
    add(ledger, 8, fitness())
    add(ledger, 9, fitness(.92, .92, .995, 95, 480))
    add(ledger, 10, fitness(.94, .94, .997, 90, 460))
    snapshot = ledger.snapshot()
    assert snapshot.improvement_streak == 2
    assert snapshot.generations == (8, 9, 10)
    assert ledger.snapshot().digest == snapshot.digest
