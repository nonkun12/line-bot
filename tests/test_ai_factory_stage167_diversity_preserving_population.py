from dataclasses import replace
import hashlib

import pytest

from core.ai_factory_stage166_recursive_policy_revision import (
    NextGenerationCandidate, RecursivePolicyRevisionReport, RevisedStrategyPrior,
)
from core.ai_factory_stage167_diversity_preserving_population import (
    EvolutionaryPopulationDiversityError, EvolutionaryPopulationDiversifier,
)


def make_revision(candidates=None, revisions=None):
    candidates = candidates if candidates is not None else (
        NextGenerationCandidate("a1", "slerp", .08, True, True, "a" * 64),
        NextGenerationCandidate("a2", "slerp", .08, True, True, "b" * 64),
        NextGenerationCandidate("b1", "ties", .04, True, True, "c" * 64),
        NextGenerationCandidate("c1", "dare", .02, True, True, "d" * 64),
        NextGenerationCandidate("d1", "lora", -.01, True, True, "e" * 64),
    )
    revisions = revisions if revisions is not None else (
        RevisedStrategyPrior("slerp", .07, .08, 4, 3, 0, 0, 1, .8, True),
        RevisedStrategyPrior("ties", .03, .04, 3, 2, 0, 0, 1, .6, True),
        RevisedStrategyPrior("dare", .02, .02, 2, 1, 0, 0, 1, .4, True),
        RevisedStrategyPrior("lora", 0, -.01, 1, 0, 0, 0, 1, .2, True),
    )
    # Stage 166's report digest is content-derived; use the exact canonical payload.
    import json
    payload = {
        "policy": "1" * 64, "feedback": "2" * 64, "tournament": "3" * 64,
        "suite": "4" * 64, "source_generation": 7,
        "revisions": [{
            "strategy": x.strategy, "previous": x.previous_prior,
            "revised": x.revised_prior, "observations": x.observations,
            "improved": x.improved, "regressed": x.regressed,
            "safety_failures": x.safety_failures, "stagnant": x.stagnant,
            "confidence": x.confidence, "retention": x.candidate_retention_eligible,
        } for x in revisions],
        "candidates": [{
            "candidate": x.candidate_id, "strategy": x.strategy,
            "prior": x.revised_prior, "score": x.evidence_score_digest,
        } for x in candidates],
        "guidance": ["verified evidence"],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return RecursivePolicyRevisionReport(
        "1" * 64, "2" * 64, "3" * 64, "4" * 64, 7, 8,
        tuple(revisions), tuple(candidates), ("verified evidence",), digest,
    )


def test_cohort_preserves_strategy_breadth_before_second_slots():
    cohort = EvolutionaryPopulationDiversifier().build(
        make_revision(), max_cohort_size=4, max_per_strategy=2, minimum_strategy_coverage=3
    )
    assert cohort.proposed_generation == 8
    assert cohort.represented_strategy_count == 4
    assert cohort.available_strategy_count == 4
    assert cohort.diversity_ratio == 1.0
    assert [x.candidate_id for x in cohort.candidates] == ["a1", "b1", "c1", "d1"]
    assert cohort.deferred_candidate_ids == ("a2",)
    assert cohort.proposal_only and not cohort.candidate_selection_authorized
    assert not cohort.experiment_execution_authorized and not cohort.model_merge_authorized
    assert not cohort.weight_mutation_authorized and not cohort.generation_advanced
    assert not cohort.model_activated and not cohort.production_switch_authorized


def test_prioritizes_remaining_slots_without_exceeding_per_strategy_cap():
    cohort = EvolutionaryPopulationDiversifier().build(
        make_revision(), max_cohort_size=5, max_per_strategy=2, minimum_strategy_coverage=2
    )
    assert len(cohort.candidates) == 5
    assert sum(x.strategy == "slerp" for x in cohort.candidates) == 2
    assert cohort.represented_strategy_count == 4


def test_empty_candidate_set_is_a_valid_empty_proposal():
    cohort = EvolutionaryPopulationDiversifier().build(make_revision(candidates=()))
    assert cohort.candidates == ()
    assert cohort.deferred_candidate_ids == ()
    assert cohort.diversity_ratio == 0.0


def test_rejects_tampered_report_authority_and_unsafe_candidates():
    revision = make_revision()
    with pytest.raises(EvolutionaryPopulationDiversityError, match="digest"):
        EvolutionaryPopulationDiversifier().build(replace(revision, digest="9" * 64))
    with pytest.raises(EvolutionaryPopulationDiversityError, match="authority"):
        EvolutionaryPopulationDiversifier().build(replace(revision, model_activated=True))
    unsafe = replace(revision.next_generation_candidates[0], repeatable=False)
    with pytest.raises(EvolutionaryPopulationDiversityError, match="non-Pareto"):
        EvolutionaryPopulationDiversifier().build(
            make_revision(candidates=(unsafe,) + revision.next_generation_candidates[1:])
        )


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_safety_gates_fail_closed(flags):
    with pytest.raises(EvolutionaryPopulationDiversityError):
        EvolutionaryPopulationDiversifier().build(make_revision(), **flags)


def test_rejects_duplicate_candidate_or_score_digest_and_strategy_retention_failure():
    revision = make_revision()
    duplicate = revision.next_generation_candidates + (revision.next_generation_candidates[0],)
    with pytest.raises(EvolutionaryPopulationDiversityError, match="duplicate"):
        EvolutionaryPopulationDiversifier().build(make_revision(candidates=duplicate))
    blocked_prior = replace(revision.revised_priors[0], candidate_retention_eligible=False)
    with pytest.raises(EvolutionaryPopulationDiversityError, match="retention"):
        EvolutionaryPopulationDiversifier().build(
            make_revision(revisions=(blocked_prior,) + revision.revised_priors[1:])
        )
