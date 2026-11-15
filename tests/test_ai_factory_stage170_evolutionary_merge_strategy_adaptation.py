from dataclasses import replace

import pytest

from core.ai_factory_stage168_generation_survival_reexploration import (
    CandidateFate, GenerationSurvivalProposal,
)
from core.ai_factory_stage169_lineage_survival_ledger import (
    EvolutionaryLineageLedgerBuilder, proposal_digest,
)
from core.ai_factory_stage170_evolutionary_merge_strategy_adaptation import (
    EvolutionaryMergeStrategyAdapter, MergeStrategyAdaptationError,
)


def make_ledger():
    def report(generation, cohort, fates):
        draft = GenerationSurvivalProposal(
            cohort, "a" * 64, generation - 1, generation, tuple(fates), (),
            sum(x.status == "SURVIVE" for x in fates),
            sum(x.status == "RETIRE" for x in fates), 0, "0" * 64,
        )
        return replace(draft, digest=proposal_digest(draft))

    def fate(candidate, strategy, status):
        return CandidateFate(candidate, strategy, status, 3, 2, .02, .99, 1.0, 1.0, "verified")

    return EvolutionaryLineageLedgerBuilder().build((
        report(5, "b" * 64, [
            fate("a1", "slerp", "SURVIVE"), fate("a2", "slerp", "SURVIVE"),
            fate("b1", "ties", "REEXPLORE"), fate("c1", "multi_model_orchestration", "SURVIVE"),
        ]),
        report(6, "c" * 64, [
            fate("a1", "slerp", "SURVIVE"), fate("a3", "slerp", "SURVIVE"),
            fate("b2", "ties", "RETIRE"), fate("c2", "multi_model_orchestration", "SURVIVE"),
        ]),
    ))


def test_adapts_strategy_portfolio_from_verified_history():
    plan = EvolutionaryMergeStrategyAdapter().build(make_ledger())
    strategies = {x.strategy: x for x in plan.allocations}
    assert strategies["slerp"].priority_score > strategies["ties"].priority_score
    assert strategies["multi_model_orchestration"].strategy_class == "ORCHESTRATION_ONLY"
    assert strategies["multi_model_orchestration"].evaluation_share > 0
    assert plan.parameter_merge_share > 0
    assert plan.orchestration_share > 0
    assert plan.parameter_merge_share + plan.orchestration_share + plan.exploration_share == pytest.approx(1.0)
    assert plan.target_generation == plan.source_generation + 1
    assert plan.proposal_only and not plan.strategy_selection_authorized
    assert not plan.experiment_execution_authorized and not plan.model_merge_authorized
    assert not plan.weight_mutation_authorized and not plan.generation_advanced


def test_rejects_tampered_ledger_and_forbidden_authority():
    ledger = make_ledger()
    with pytest.raises(MergeStrategyAdaptationError, match="digest"):
        EvolutionaryMergeStrategyAdapter().build(replace(ledger, digest="f" * 64))
    with pytest.raises(MergeStrategyAdaptationError, match="authority"):
        EvolutionaryMergeStrategyAdapter().build(replace(ledger, generation_advanced=True))


def test_rejects_invalid_strategy_metrics_and_empty_history():
    ledger = make_ledger()
    bad_strategy = replace(ledger.strategy_history[0], survival_rate=.99)
    with pytest.raises(MergeStrategyAdaptationError, match="rate"):
        EvolutionaryMergeStrategyAdapter().build(
            replace(ledger, strategy_history=(bad_strategy,) + ledger.strategy_history[1:])
        )
    with pytest.raises(MergeStrategyAdaptationError, match="no measured"):
        EvolutionaryMergeStrategyAdapter().build(replace(ledger, strategy_history=()))


@pytest.mark.parametrize("flags", [
    {"hold_active": True}, {"kill_switch_active": True}, {"budget_available": False},
])
def test_global_gates_fail_closed(flags):
    with pytest.raises(MergeStrategyAdaptationError):
        EvolutionaryMergeStrategyAdapter().build(make_ledger(), **flags)


def test_respects_strategy_share_cap_and_bounded_exploration():
    plan = EvolutionaryMergeStrategyAdapter().build(
        make_ledger(), maximum_strategy_share=.20, exploration_floor=.15
    )
    assert all(x.evaluation_share <= .20 + 1e-9 for x in plan.allocations)
    assert plan.exploration_share >= .15
