import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage151_evolutionary_knowledge import EvolutionStrategyProposal, StrategyKind
from core.ai_factory_stage152_evolutionary_meta_learning import (
    EvolutionaryMetaLearner, MetaLearningError, StrategyTrialEvidence, TrialOutcome,
)

SUITE = "a" * 64
BASE = Fitness(.80, .80, .99, 100, 512, 0, SUITE)
BETTER = Fitness(.90, .90, .99, 90, 500, 0, SUITE)
WORSE = Fitness(.70, .70, .98, 120, 600, 1, SUITE)


def proposal(kind=StrategyKind.DIVERSIFY_PARENTS):
    return EvolutionStrategyProposal("p" * 64, kind, "test", (), (1, 2), SUITE, 90)


def evidence(n, kind=StrategyKind.DIVERSIFY_PARENTS, candidate=BETTER, suite=SUITE):
    return StrategyTrialEvidence(
        f"trial-{n}", "p" * 64, kind, suite, "independent-evaluator",
        "strategy-author", f"{n:064x}", f"{(n+100):064x}",
        f"{(n+200):064x}", BASE, candidate,
    )


def test_only_independently_verified_executed_trials_are_recorded():
    learner = EvolutionaryMetaLearner(lambda item: True, min_trials_for_ranking=2)
    learner.record(proposal(), evidence(1))
    learner.record(proposal(), evidence(2))
    snapshot = learner.snapshot()
    row = snapshot.effectiveness[0]
    assert row.ranked and row.rank == 1 and row.success_rate == 1.0
    assert all(not x.execution_authorized and not x.auto_adoption_authorized and not x.model_mutation_authorized
               for x in snapshot.effectiveness)


def test_rejects_missing_or_invalid_authentication():
    learner = EvolutionaryMetaLearner(lambda item: False)
    with pytest.raises(MetaLearningError):
        learner.record(proposal(), evidence(1))
    with pytest.raises(ValueError):
        EvolutionaryMetaLearner(None)


def test_author_cannot_evaluate_own_strategy():
    learner = EvolutionaryMetaLearner(lambda item: True)
    item = evidence(1)
    item = StrategyTrialEvidence(**{**item.__dict__, "evaluator_id": "strategy-author"})
    with pytest.raises(MetaLearningError):
        learner.record(proposal(), item)


def test_rejects_duplicate_replay_and_suite_drift():
    learner = EvolutionaryMetaLearner(lambda item: True)
    item = evidence(1)
    learner.record(proposal(), item)
    with pytest.raises(MetaLearningError):
        learner.record(proposal(), item)
    with pytest.raises(MetaLearningError):
        learner.record(proposal(), evidence(2, suite="b" * 64))


def test_classifies_regression_and_neutral_trials():
    learner = EvolutionaryMetaLearner(lambda item: True)
    assert learner.record(proposal(), evidence(1, candidate=WORSE)).outcome is TrialOutcome.REGRESSED
    neutral = Fitness(.80, .80, .99, 100, 512, 0, SUITE)
    assert learner.record(proposal(), evidence(2, candidate=neutral)).outcome is TrialOutcome.NEUTRAL


def test_strategy_rank_requires_repeated_trials_and_is_deterministic():
    learner = EvolutionaryMetaLearner(lambda item: True, min_trials_for_ranking=3)
    learner.record(proposal(), evidence(1))
    first = learner.snapshot()
    assert first.effectiveness[0].ranked is False
    learner.record(proposal(), evidence(2))
    learner.record(proposal(), evidence(3))
    a = learner.snapshot()
    b = learner.snapshot()
    assert a.digest == b.digest
    assert a.effectiveness[0].ranked and a.effectiveness[0].rank == 1


def test_capacity_is_fail_closed():
    learner = EvolutionaryMetaLearner(lambda item: True, max_trials=1)
    learner.record(proposal(), evidence(1))
    with pytest.raises(MetaLearningError):
        learner.record(proposal(), evidence(2))
