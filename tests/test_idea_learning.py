from __future__ import annotations

import pytest

from core.idea_learning import IdeaOutcome, rank_idea_styles


def test_preserves_default_order_without_experiment_evidence():
    assert rank_idea_styles(("reframe", "recombine", "specialize")) == (
        "reframe", "recombine", "specialize"
    )


def test_unverified_outcomes_do_not_change_strategy_ranking():
    styles = ("reframe", "recombine", "specialize")
    baseline = rank_idea_styles(styles)
    result = rank_idea_styles(
        styles,
        (IdeaOutcome("recombine", "unverified", "review comment only"),),
    )
    assert result == baseline


def test_verified_experiment_results_balance_exploration_and_exploitation():
    styles = ("reframe", "recombine", "specialize")
    outcomes = tuple(
        [IdeaOutcome("reframe", "success", f"benchmark-{i}") for i in range(20)]
        + [IdeaOutcome("recombine", "failure", f"benchmark-f-{i}") for i in range(20)]
    )

    ranked = rank_idea_styles(styles, outcomes)

    assert ranked[0] == "specialize"  # untested strategy gets exploration priority
    assert ranked.index("reframe") < ranked.index("recombine")


def test_rejects_unbounded_or_invalid_evidence():
    with pytest.raises(ValueError):
        IdeaOutcome("reframe", "success", "")
    with pytest.raises(ValueError):
        IdeaOutcome("reframe", "maybe", "experiment-1")
    with pytest.raises(ValueError):
        IdeaOutcome("reframe", "success", "x" * 301)


def test_idea_agent_can_use_measured_outcomes_without_enabling_execution():
    from core.idea_ai import IdeaAgent

    outcomes = tuple(
        IdeaOutcome("reframe", "failure", f"experiment-{i}") for i in range(20)
    )
    ideas = IdeaAgent().propose("improve autonomous reasoning", limit=1, outcomes=outcomes)

    assert len(ideas) == 1
    assert ideas[0].style != "reframe"
    assert "No implementation, execution, merge, deploy" in ideas[0].task.instruction
