from dataclasses import replace
import hashlib
import json

import pytest

from core.ai_factory_stage168_generation_survival_reexploration import (
    CandidateFate, GenerationSurvivalProposal,
)
from core.ai_factory_stage169_lineage_survival_ledger import (
    EvolutionaryLineageLedgerBuilder, EvolutionaryLineageLedgerError, proposal_digest,
)


def proposal(generation, cohort_digest, fates, suite="a" * 64):
    provisional = GenerationSurvivalProposal(
        cohort_digest, suite, generation - 1, generation, tuple(fates), (),
        sum(x.status == "SURVIVE" for x in fates),
        sum(x.status == "RETIRE" for x in fates), 0, "0" * 64,
    )
    return replace(provisional, digest=proposal_digest(provisional))


def fate(candidate, strategy, status):
    return CandidateFate(candidate, strategy, status, 3, 2, .02, .99, 1.0, 1.0, "verified")


def test_builds_cross_generation_candidate_and_strategy_history():
    first = proposal(5, "b" * 64, [
        fate("model-a", "slerp", "SURVIVE"),
        fate("model-b", "ties", "REEXPLORE"),
    ])
    second = proposal(6, "c" * 64, [
        fate("model-a", "slerp", "SURVIVE"),
        fate("model-c", "ties", "RETIRE"),
    ])
    ledger = EvolutionaryLineageLedgerBuilder().build((first, second))
    assert ledger.first_generation == 5
    assert ledger.latest_generation == 6
    assert ledger.generation_count == 2
    model_a = next(x for x in ledger.candidate_history if x.candidate_id == "model-a")
    assert model_a.survived_generations == 2
    assert model_a.first_seen_generation == 5 and model_a.last_seen_generation == 6
    slerp = next(x for x in ledger.strategy_history if x.strategy == "slerp")
    assert slerp.survival_rate == 1.0
    assert ledger.append_only_proposal
    assert not ledger.history_rewrite_authorized
    assert not ledger.survival_selection_authorized
    assert not ledger.model_merge_authorized and not ledger.generation_advanced


def test_rejects_suite_drift_replay_and_tampered_digest():
    first = proposal(5, "b" * 64, [fate("model-a", "slerp", "SURVIVE")])
    with pytest.raises(EvolutionaryLineageLedgerError, match="suite"):
        EvolutionaryLineageLedgerBuilder().build((
            first, proposal(6, "c" * 64, [fate("model-b", "ties", "SURVIVE")], suite="d" * 64)
        ))
    with pytest.raises(EvolutionaryLineageLedgerError, match="replay"):
        EvolutionaryLineageLedgerBuilder().build((
            first, proposal(6, "b" * 64, [fate("model-b", "ties", "SURVIVE")])
        ))
    with pytest.raises(EvolutionaryLineageLedgerError, match="digest"):
        EvolutionaryLineageLedgerBuilder().build((replace(first, digest="f" * 64),))


def test_rejects_generation_gap_and_candidate_strategy_drift():
    five = proposal(5, "b" * 64, [fate("model-a", "slerp", "SURVIVE")])
    seven = proposal(7, "c" * 64, [fate("model-a", "slerp", "SURVIVE")])
    with pytest.raises(EvolutionaryLineageLedgerError, match="contiguous"):
        EvolutionaryLineageLedgerBuilder().build((five, seven))
    six = proposal(6, "d" * 64, [fate("model-a", "ties", "SURVIVE")])
    with pytest.raises(EvolutionaryLineageLedgerError, match="strategy"):
        EvolutionaryLineageLedgerBuilder().build((five, six))


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_safety_gates_fail_closed(flags):
    report = proposal(5, "b" * 64, [fate("model-a", "slerp", "SURVIVE")])
    with pytest.raises(EvolutionaryLineageLedgerError):
        EvolutionaryLineageLedgerBuilder().build((report,), **flags)


def test_rejects_forbidden_authority_and_duplicate_candidate_fate():
    report = proposal(5, "b" * 64, [fate("model-a", "slerp", "SURVIVE")])
    with pytest.raises(EvolutionaryLineageLedgerError, match="authority"):
        EvolutionaryLineageLedgerBuilder().build((replace(report, generation_advanced=True),))
    duplicate = proposal(5, "c" * 64, [
        fate("model-a", "slerp", "SURVIVE"), fate("model-a", "slerp", "RETIRE")
    ])
    with pytest.raises(EvolutionaryLineageLedgerError, match="duplicate"):
        EvolutionaryLineageLedgerBuilder().build((duplicate,))
