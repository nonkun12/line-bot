from dataclasses import replace

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage156_authenticated_knowledge_transfer import (
    GenerationKnowledge, KnowledgeTransferSnapshot,
)
from core.ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)
from core.ai_factory_stage161_verified_evolution_feedback import (
    EvolutionFeedbackReceipt, EvolutionFeedbackSnapshot,
)
from core.ai_factory_stage162_evolutionary_policy_learning import (
    EvolutionPolicyError, EvolutionarySelectionPolicyLearner,
    EvolutionaryTournamentPolicyAdvisor,
)

SUITE = "a" * 64


def make_record(strategy="slerp", generation=2, suffix="1"):
    fitness = Fitness(.94, .93, .99, 80, 420, 0, SUITE)
    digest = suffix * 64
    return GenerationKnowledge(
        transfer_id=("b" if suffix != "b" else "c") * 64,
        source_generation=generation - 1,
        proposed_generation=generation,
        source_candidate_id=f"candidate-{suffix}",
        parent_model_ids=("parent-a", "parent-b"),
        parent_artifact_digests=("d" * 64, "e" * 64),
        candidate_artifact_digest="f" * 64,
        evaluation_suite_digest=SUITE,
        recipe_digest="9" * 64,
        strategy=strategy,
        fitness=fitness,
        outcome_digest=("2" if suffix != "2" else "3") * 64,
        evidence_digest=("4" if suffix != "4" else "5") * 64,
        evaluator_id=f"evaluator-{suffix}",
        lessons=("accuracy improved",),
        record_digest=digest,
    )


def make_feedback(records=None):
    records = records or (make_record(),)
    receipts = tuple(EvolutionFeedbackReceipt(
        proposal_id=f"proposal-{i}",
        proposal_digest="6" * 64,
        source_outcome_digest=record.outcome_digest,
        knowledge_transfer_id=record.transfer_id,
        knowledge_record_digest=record.record_digest,
        feedback_digest=("7" if i == 0 else "8") * 64,
        proposed_generation=record.proposed_generation,
    ) for i, record in enumerate(records))
    knowledge = KnowledgeTransferSnapshot(
        records, tuple(x.source_generation for x in records),
        tuple(x.proposed_generation for x in records), "9" * 64,
    )
    return EvolutionFeedbackSnapshot(receipts, knowledge, "a" * 64)


def make_tournament():
    from core.ai_factory_stage141_evolution import Fitness
    fitness = Fitness(.93, .92, .99, 85, 450, 0, SUITE)
    scores = (
        StrategyScore("candidate-a", "slerp", 2, ("eval-a", "eval-b"), fitness, True, (), True, "1" * 64),
        StrategyScore("candidate-b", "ties", 2, ("eval-c", "eval-d"), fitness, True, (), True, "2" * 64),
    )
    return MergeTournamentReport(
        "3" * 64, SUITE, scores,
        (("candidate-b", "ties"), ("candidate-a", "slerp")), (), "4" * 64,
    )


def test_learns_digest_bound_bounded_policy_from_stage161_records():
    feedback = make_feedback((make_record("slerp", 2, "1"), make_record("ties", 3, "2")))
    policy = EvolutionarySelectionPolicyLearner().learn(feedback, expected_suite_digest=SUITE)
    assert {x.strategy for x in policy.learnings} == {"slerp", "ties"}
    assert all(x.observations == x.improved_observations == 1 for x in policy.learnings)
    assert all(abs(x.prior_score) <= .15 for x in policy.learnings)
    assert policy.proposal_only is True
    assert policy.selection_authorized is False
    assert policy.model_activated is False


def test_advisor_only_reorders_pareto_eligible_tournament_candidates():
    feedback = make_feedback()
    policy = EvolutionarySelectionPolicyLearner().learn(feedback, expected_suite_digest=SUITE)
    advice = EvolutionaryTournamentPolicyAdvisor().rank(make_tournament(), policy)
    assert set(advice.ordered_preferences) == {
        ("candidate-a", "slerp"), ("candidate-b", "ties")
    }
    assert advice.proposal_only is True
    assert advice.selection_authorized is False
    assert advice.model_activated is False


def test_rejects_receipt_mismatch_and_suite_drift():
    feedback = make_feedback()
    bad_receipt = replace(feedback.receipts[0], knowledge_record_digest="f" * 64)
    with pytest.raises(EvolutionPolicyError, match="receipt"):
        EvolutionarySelectionPolicyLearner().learn(
            replace(feedback, receipts=(bad_receipt,)), expected_suite_digest=SUITE
        )
    with pytest.raises(EvolutionPolicyError, match="suite drift"):
        EvolutionarySelectionPolicyLearner().learn(
            feedback, expected_suite_digest="b" * 64
        )


def test_rejects_replayed_records_and_forbidden_authority():
    feedback = make_feedback()
    duplicate = replace(feedback.knowledge, records=(feedback.knowledge.records[0],)*2)
    with pytest.raises(EvolutionPolicyError, match="exactly one|duplicate"):
        EvolutionarySelectionPolicyLearner().learn(
            replace(feedback, knowledge=duplicate), expected_suite_digest=SUITE
        )
    unsafe = replace(feedback, model_activated=True)
    with pytest.raises(EvolutionPolicyError, match="forbidden authority"):
        EvolutionarySelectionPolicyLearner().learn(unsafe, expected_suite_digest=SUITE)


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_policy_learning_fails_closed(flags):
    with pytest.raises(EvolutionPolicyError):
        EvolutionarySelectionPolicyLearner().learn(
            make_feedback(), expected_suite_digest=SUITE, **flags
        )


def test_prior_cannot_promote_dominated_or_nonrepeatable_candidates():
    feedback = make_feedback()
    policy = EvolutionarySelectionPolicyLearner().learn(feedback, expected_suite_digest=SUITE)
    tournament = make_tournament()
    bad_score = replace(tournament.scores[0], pareto_optimal=False)
    filtered = replace(tournament, scores=(bad_score, tournament.scores[1]))
    advice = EvolutionaryTournamentPolicyAdvisor().rank(filtered, policy)
    assert advice.ordered_preferences == (("candidate-b", "ties"),)
