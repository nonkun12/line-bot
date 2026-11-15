from dataclasses import replace
import hashlib
import json

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage158_evolutionary_merge_tournament import (
    MergeTournamentReport, StrategyScore,
)
from core.ai_factory_stage162_evolutionary_policy_learning import (
    EvolutionarySelectionPolicy, StrategyLearning,
)
from core.ai_factory_stage165_recursive_evolution_feedback import (
    RecursiveEvolutionFeedbackSnapshot, RecursiveTrialRecord, StrategyEvolutionSummary,
)
from core.ai_factory_stage166_recursive_model_selection import (
    RecursiveModelSelectionAdvisor, RecursiveModelSelectionError,
)

SUITE = "a" * 64


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def make_record(strategy, classification, n):
    metrics = (("accuracy", .94), ("instruction_following", .93), ("latency_ms", 80.0),
               ("memory_mb", 450.0), ("regression_count", 0.0), ("safety", .99))
    baseline = (("accuracy", .91), ("instruction_following", .90), ("latency_ms", 90.0),
                ("memory_mb", 500.0), ("regression_count", 0.0), ("safety", .98))
    lessons = ("verified lesson",)
    canonical = {
        "outcome": f"{n:064x}", "evidence": f"{n+100:064x}", "design": "b" * 64,
        "plan": f"plan-{n}", "recipe": "c" * 64, "strategy": strategy,
        "generation": 7, "classification": classification,
        "metrics": metrics, "baseline": baseline, "lessons": list(lessons),
    }
    record_digest = digest(canonical)
    return RecursiveTrialRecord(
        canonical["outcome"], canonical["evidence"], canonical["design"],
        canonical["plan"], canonical["recipe"], strategy, 7, 8,
        classification, metrics, baseline, lessons, record_digest,
    )


def make_snapshot(records):
    grouped = {}
    for r in records:
        grouped.setdefault(r.strategy, []).append(r)
    summaries = []
    for strategy, items in sorted(grouped.items()):
        counts = [len(items), sum(x.classification == "IMPROVED" for x in items),
                  sum(x.classification == "REGRESSED" for x in items),
                  sum(x.classification == "SAFETY_FAILURE" for x in items),
                  sum(x.classification == "STAGNANT" for x in items)]
        summaries.append(StrategyEvolutionSummary(
            strategy, *counts, max(0, counts[0] * 2 - counts[1]), ("guidance",)
        ))
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
    return RecursiveEvolutionFeedbackSnapshot(tuple(records), tuple(summaries), SUITE, digest(payload))


def make_policy():
    learning = StrategyLearning("slerp", 5, 4, .94, .99, 80, 450, .8, .08, ("d" * 64,))
    policy = EvolutionarySelectionPolicy("e" * 64, SUITE, (learning,), "")
    payload = {
        "feedback": policy.feedback_snapshot_digest, "suite": SUITE,
        "learnings": [{
            "strategy": x.strategy, "count": x.observations,
            "improved": x.improved_observations, "quality": x.quality_mean,
            "safety": x.safety_mean, "latency": x.latency_mean_ms,
            "memory": x.memory_mean_mb, "confidence": x.confidence,
            "prior": x.prior_score, "records": list(x.evidence_record_digests),
        } for x in policy.learnings],
    }
    return replace(policy, policy_digest=digest(payload))


def make_tournament():
    fit = Fitness(.96, .95, .99, 75, 440, 0, SUITE)
    score = StrategyScore("candidate-a", "slerp", 3, ("eval-a", "eval-b", "eval-c"),
                          fit, True, (), True, "f" * 64)
    return MergeTournamentReport("1" * 64, SUITE, (score,),
                                  (("candidate-a", "slerp"),), (), "2" * 64)


def test_failure_informed_advice_reweights_only_pareto_repeatable_candidates():
    snapshot = make_snapshot([
        make_record("slerp", "IMPROVED", 1),
        make_record("slerp", "IMPROVED", 2),
        make_record("slerp", "REGRESSED", 3),
        make_record("slerp", "STAGNANT", 4),
    ])
    result = RecursiveModelSelectionAdvisor().rank(snapshot, make_policy(), make_tournament())
    assert result.ordered_preferences == (("candidate-a", "slerp"),)
    advice = result.advice[0]
    assert advice.evidence_observations == 4
    assert advice.improved_observations == 2 and advice.regression_observations == 1
    assert advice.recursive_feedback_adjustment > 0
    assert advice.combined_score <= .15
    assert result.proposal_only and not result.candidate_selection_authorized
    assert not result.model_mutation_authorized and not result.generation_advanced


def test_safety_failure_reduces_strategy_priority():
    snapshot = make_snapshot([
        make_record("slerp", "SAFETY_FAILURE", 5),
        make_record("slerp", "SAFETY_FAILURE", 6),
    ])
    result = RecursiveModelSelectionAdvisor().rank(snapshot, make_policy(), make_tournament())
    assert result.advice[0].safety_failures == 2
    assert result.advice[0].recursive_feedback_adjustment < 0


def test_never_promotes_dominated_unsafe_or_unrepeatable_score():
    snapshot = make_snapshot([make_record("slerp", "IMPROVED", 7)])
    tournament = make_tournament()
    unsafe = replace(tournament.scores[0], median_fitness=Fitness(.99, .99, .90, 50, 400, 0, SUITE))
    report = replace(tournament, scores=(unsafe,))
    result = RecursiveModelSelectionAdvisor().rank(snapshot, make_policy(), report)
    assert result.ordered_preferences == () and result.advice == ()


def test_rejects_tampered_snapshot_or_suite_drift():
    snapshot = make_snapshot([make_record("slerp", "IMPROVED", 8)])
    with pytest.raises(RecursiveModelSelectionError, match="digest"):
        RecursiveModelSelectionAdvisor().rank(replace(snapshot, digest="9" * 64), make_policy(), make_tournament())
    with pytest.raises(RecursiveModelSelectionError, match="frozen suite"):
        RecursiveModelSelectionAdvisor().rank(snapshot, replace(make_policy(), evaluation_suite_digest="8" * 64), make_tournament())


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_gates_fail_closed(flags):
    snapshot = make_snapshot([make_record("slerp", "IMPROVED", 9)])
    with pytest.raises(RecursiveModelSelectionError):
        RecursiveModelSelectionAdvisor().rank(snapshot, make_policy(), make_tournament(), **flags)


def test_rejects_tampered_record_and_policy_digest():
    snapshot = make_snapshot([make_record("slerp", "IMPROVED", 10)])
    tampered = replace(snapshot.records[0], classification="SAFETY_FAILURE")
    with pytest.raises(RecursiveModelSelectionError, match="record digest"):
        RecursiveModelSelectionAdvisor().rank(replace(snapshot, records=(tampered,)), make_policy(), make_tournament())
    policy = make_policy()
    with pytest.raises(RecursiveModelSelectionError, match="policy"):
        RecursiveModelSelectionAdvisor().rank(snapshot, replace(policy, policy_digest="7" * 64), make_tournament())
