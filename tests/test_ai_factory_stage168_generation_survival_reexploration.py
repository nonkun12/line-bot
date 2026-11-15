from dataclasses import replace

import pytest

from core.ai_factory_stage167_diversity_preserving_population import (
    CohortCandidate, EvolutionaryPopulationCohort,
)
from core.ai_factory_stage168_generation_survival_reexploration import (
    CandidateEvaluationEvidence, GenerationSurvivalError,
    GenerationSurvivalEvaluator, evidence_digest,
)

SUITE = "a" * 64
COHORT_DIGEST = "b" * 64
METRICS = (
    ("accuracy", .90), ("instruction_following", .92), ("safety", .99),
    ("latency_ms", 100.0), ("memory_mb", 512.0), ("regression_count", 0.0),
)
BASELINE = (
    ("accuracy", .88), ("instruction_following", .90), ("safety", .99),
    ("latency_ms", 100.0), ("memory_mb", 512.0), ("regression_count", 0.0),
)


def cohort():
    return EvolutionaryPopulationCohort(
        "c" * 64, SUITE, 4, 5,
        (CohortCandidate("candidate-a", "slerp", .05, "d" * 64, 1, 1),
         CohortCandidate("candidate-b", "ties", .02, "e" * 64, 2, 2)),
        (), (), 2, 2, 1.0, COHORT_DIGEST,
    )


def record(candidate, evaluator, *, metrics=METRICS, baseline=BASELINE, signature=None):
    item = CandidateEvaluationEvidence(
        candidate, "slerp" if candidate == "candidate-a" else "ties",
        COHORT_DIGEST, SUITE, 5, evaluator, "trusted-key-" + evaluator,
        signature or "sig-" + candidate + "-" + evaluator, metrics, baseline,
    )
    return item


def evaluate(items, **kwargs):
    return GenerationSurvivalEvaluator().evaluate(
        cohort(), tuple(items), verify_signature=lambda key, digest, signature: True, **kwargs
    )


def test_improved_candidate_survives_and_stagnant_candidate_is_reexplored():
    improved = [record("candidate-a", "eval-1"), record("candidate-a", "eval-2")]
    stagnant_metrics = (
        ("accuracy", .88), ("instruction_following", .90), ("safety", .99),
        ("latency_ms", 100.0), ("memory_mb", 512.0), ("regression_count", 0.0),
    )
    stagnant = [
        record("candidate-b", "eval-3", metrics=stagnant_metrics),
        record("candidate-b", "eval-4", metrics=stagnant_metrics),
    ]
    result = evaluate(improved + stagnant)
    fates = {x.candidate_id: x.status for x in result.fates}
    assert fates == {"candidate-a": "SURVIVE", "candidate-b": "REEXPLORE"}
    assert result.reexploration_count == 1
    assert result.proposal_only and not result.survival_selection_authorized
    assert not result.retirement_executed and not result.model_merge_authorized
    assert not result.weight_mutation_authorized and not result.generation_advanced


def test_safety_failure_and_resource_regression_propose_retirement():
    unsafe = tuple((k, .80 if k == "safety" else v) for k, v in METRICS)
    resource = tuple((k, 120.0 if k == "latency_ms" else v) for k, v in METRICS)
    result = evaluate([
        record("candidate-a", "eval-1", metrics=unsafe),
        record("candidate-a", "eval-2", metrics=unsafe),
        record("candidate-b", "eval-3", metrics=resource),
        record("candidate-b", "eval-4", metrics=resource),
    ])
    assert all(x.status == "RETIRE" for x in result.fates)
    assert result.retirement_count == 2
    assert result.retirement_executed is False


def test_insufficient_repeats_requests_reexploration():
    result = evaluate([record("candidate-a", "eval-1")])
    fate = next(x for x in result.fates if x.candidate_id == "candidate-a")
    assert fate.status == "REEXPLORE"
    assert fate.repeat_count == 1


def test_rejects_lineage_replay_and_bad_signature():
    item = record("candidate-a", "eval-1")
    with pytest.raises(GenerationSurvivalError, match="lineage"):
        evaluate([replace(item, cohort_digest="f" * 64), record("candidate-a", "eval-2")])
    with pytest.raises(GenerationSurvivalError, match="signature"):
        GenerationSurvivalEvaluator().evaluate(
            cohort(), (item,), verify_signature=lambda key, digest, signature: False
        )
    with pytest.raises(GenerationSurvivalError, match="replayed"):
        evaluate([item, item])


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_gates_fail_closed(flags):
    with pytest.raises(GenerationSurvivalError):
        evaluate([], **flags)


def test_requires_distinct_evaluators_and_frozen_suite():
    repeated_same = [record("candidate-a", "eval-1", signature="sig1"),
                     record("candidate-a", "eval-1", signature="sig2")]
    result = evaluate(repeated_same)
    fate = next(x for x in result.fates if x.candidate_id == "candidate-a")
    assert fate.status == "REEXPLORE"
    assert fate.evaluator_count == 1
    with pytest.raises(GenerationSurvivalError, match="lineage"):
        evaluate([record("candidate-a", "eval-1"),
                  replace(record("candidate-a", "eval-2"), evaluation_suite_digest="f" * 64)])


def test_evidence_digest_is_stable_and_bound_to_metrics():
    item = record("candidate-a", "eval-1")
    assert evidence_digest(item) == evidence_digest(item)
    changed = replace(item, metrics=BASELINE)
    assert evidence_digest(item) != evidence_digest(changed)
