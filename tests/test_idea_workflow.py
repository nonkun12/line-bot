from __future__ import annotations

import pytest

from core.idea_workflow import build_idea_workflow
from core.multi_agent import AgentRole


def test_builds_separate_ideation_critique_and_synthesis_stages():
    batches = build_idea_workflow(
        "improve autonomous research",
        context=("free/local-first", "fail closed"),
    )

    assert len(batches) == 3
    ideate, critique, synthesize = (batch.tasks[0] for batch in batches)
    assert ideate.role is AgentRole.IDEA
    assert critique.role is AgentRole.REVIEWER
    assert synthesize.role is AgentRole.INTEGRATOR
    assert critique.depends_on == (ideate.task_id,)
    assert synthesize.depends_on == (critique.task_id,)
    assert "unconventional" in ideate.instruction
    assert "counterexamples" in critique.instruction
    assert "success/failure criteria" in synthesize.instruction


def test_every_stage_is_explicitly_non_executing():
    batches = build_idea_workflow("develop a better evaluator")
    tasks = [task for batch in batches for task in batch.tasks]

    assert len(tasks) == 3
    assert all("Do not implement" in task.instruction for task in tasks)
    assert all("execute" in task.instruction for task in tasks)
    assert all("merge" in task.instruction and "deploy" in task.instruction for task in tasks)


def test_context_is_bounded_and_invalid_input_is_rejected():
    batches = build_idea_workflow(
        "bounded focus",
        context=tuple(f"item-{index}" for index in range(20)),
    )
    assert len(batches[0].tasks[0].instruction) < 4000

    with pytest.raises(ValueError):
        build_idea_workflow(" ")
    with pytest.raises(ValueError):
        build_idea_workflow("x" * 4001)
    with pytest.raises(ValueError):
        build_idea_workflow("valid", context=["not", "a", "tuple"])
    with pytest.raises(ValueError):
        build_idea_workflow("valid", context=(1,))
