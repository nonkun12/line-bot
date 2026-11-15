from dataclasses import replace
import hashlib
import json

import pytest

from core.ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)
from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage162_evolutionary_policy_learning import (
    EvolutionarySelectionPolicy, StrategyLearning,
)
from core.ai_factory_stage165_recursive_evolution_feedback import (
    RecursiveEvolutionFeedbackSnapshot, RecursiveTrialRecord, StrategyEvolutionSummary,
)
from core.ai_factory_stage166_recursive_policy_revision import (
    RecursiveEvolutionPolicyReviser, RecursivePolicyRevisionError,
)

SUITE = "a" * 64


def make_snapshot(classifications=("IMPROVED", "REGRESSED", "SAFETY_FAILURE", "STAGNANT")):
    records = []
    for i, classification in enumerate(classifications):
        strategy = ("slerp", "ties", "dare", "lora")[i]
        metrics = (("accuracy", .92), ("instruction_following", .91), ("safety", .99),
                   ("latency_ms", 85.0), ("memory_mb", 480.0), ("regression_count", 0.0))
        records.append(RecursiveTrialRecord(
            hashlib.sha256(f"outcome-{i}".encode()).hexdigest(),
            hashlib.sha256(f"evidence-{i}".encode()).hexdigest(),
            "b" * 64, f"plan-{i}", "c" * 64, strategy, 7, 8,
            classification, metrics, metrics, ("verified lesson",),
            hashlib.sha256(f"record-{i}".encode()).hexdigest(),
        ))
    grouped = {}
    for record in records:
        grouped.setdefault(record.strategy, []).append(record)
    summaries = tuple(StrategyEvolutionSummary(
        strategy, len(items),
        sum(x.classification == "IMPROVED" for x in items),
        sum(x.classification == "REGRESSED" for x in items),
        sum(x.classification == "SAFETY_FAILURE" for x in items),
        sum(x.classification == "STAGNANT" for x in items),
        len(items) * 2 - sum(x.classification == "IMPROVED" for x in items),
        ("verified feedback",),
    ) for strategy, items in sorted(grouped.items()))
    payload = {
        "records": [x.record_digest for x in records],
        "summaries": [{
            "strategy": x.strategy, "observations": x.observations,
            "improved": x.improved, "regressed": x.regressed,
            "safety_failures": x.safety_failures, "stagnant": x.stagnant,
            "repeatability_required": x.repeatability_required,
            "guidance": list(x.next_generation_guidance),
        } for x in summaries],
        "suite": SUITE,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return RecursiveEvolutionFeedbackSnapshot(tuple(records), summaries, SUITE, digest)


def make_policy():
    learning = (
        StrategyLearning("slerp", 3, 2, .92, .99, 90, 500, .6, .08, ("d" * 64,)),
        StrategyLearning("ties", 2, 1, .90, .98, 100, 510, .4, .04, ("e" * 64,)),
    )
    return EvolutionarySelectionPolicy("f" * 64, SUITE, learning, "1" * 64)


def make_tournament():
    def score(candidate, strategy, safety=.99, regression=0):
        fitness = Fitness(.94, .93, safety, 80, 450, regression, SUITE)
        return StrategyScore(candidate, strategy, 3, ("e1", "e2", "e3"), fitness,
                             True, (), True, hashlib.sha256(f"{candidate}-{strategy}".encode()).hexdigest())
    scores = (score("candidate-a", "slerp"), score("candidate-b", "ties"),
              score("candidate-c", "dare", .90), score("candidate-d", "lora"))
    return MergeTournamentReport(
        "2" * 64, SUITE, scores,
        (("candidate-a", "slerp"), ("candidate-b", "ties"),
         ("candidate-c", "dare"), ("candidate-d", "lora")),
        (), "3" * 64,
    )


def test_recursive_revision_rewards_wins_penalizes_failures_and_filters_candidates():
    result = RecursiveEvolutionPolicyReviser().revise(make_policy(), make_snapshot(), make_tournament())
    priors = {x.strategy: x for x in result.revised_priors}
    assert priors["slerp"].revised_prior > priors["slerp"].previous_prior
    assert priors["ties"].revised_prior < priors["ties"].previous_prior
    assert priors["dare"].candidate_retention_eligible is False
    assert priors["lora"].revised_prior < 0
    assert [(x.candidate_id, x.strategy) for x in result.next_generation_candidates] == [
        ("candidate-a", "slerp"), ("candidate-b", "ties")
    ]
    assert result.proposed_generation == 8
    assert result.proposal_only and not result.candidate_selection_authorized
    assert not result.experiment_execution_authorized and not result.model_mutation_authorized
    assert not result.generation_advanced and not result.model_activated
    assert not result.production_switch_authorized


def test_no_feedback_preserves_policy_and_does_not_create_candidate():
    snapshot = make_snapshot(())
    result = RecursiveEvolutionPolicyReviser().revise(make_policy(), snapshot, make_tournament())
    assert all(x.previous_prior == x.revised_prior for x in result.revised_priors)
    assert result.next_generation_candidates == ()
    assert "no verified Stage 165 trials" in result.exploration_guidance[0]


def test_rejects_suite_drift_tampering_and_forbidden_authority():
    with pytest.raises(RecursivePolicyRevisionError, match="suite"):
        RecursiveEvolutionPolicyReviser().revise(
            make_policy(), make_snapshot(), replace(make_tournament(), evaluation_suite_digest="9" * 64)
        )
    with pytest.raises(RecursivePolicyRevisionError, match="digest"):
        RecursiveEvolutionPolicyReviser().revise(
            make_policy(), replace(make_snapshot(), digest="8" * 64), make_tournament()
        )
    with pytest.raises(RecursivePolicyRevisionError, match="authority"):
        RecursiveEvolutionPolicyReviser().revise(
            make_policy(), replace(make_snapshot(), model_activated=True), make_tournament()
        )


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_gates_fail_closed(flags):
    with pytest.raises(RecursivePolicyRevisionError):
        RecursiveEvolutionPolicyReviser().revise(make_policy(), make_snapshot(), make_tournament(), **flags)


def test_revision_is_bounded_and_deterministic():
    reviser = RecursiveEvolutionPolicyReviser()
    first = reviser.revise(make_policy(), make_snapshot(), make_tournament())
    second = reviser.revise(make_policy(), make_snapshot(), make_tournament())
    assert first == second
    assert all(abs(x.revised_prior - x.previous_prior) <= .05 for x in first.revised_priors)
    with pytest.raises(RecursivePolicyRevisionError, match="max_prior_delta"):
        reviser.revise(make_policy(), make_snapshot(), make_tournament(), max_prior_delta=.10)
