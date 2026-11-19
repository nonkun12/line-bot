"""Safe, role-separated workflow planning for empirical idea development.

This module creates an orchestration plan only. It does not invoke agents,
execute experiments, modify files, or grant implementation permissions.
"""
from __future__ import annotations

from core.multi_agent import AgentRole, AgentTask, TaskBatch, plan_batches

_MAX_FOCUS_CHARS = 4000
_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 500


def build_idea_workflow(
    focus: str,
    *,
    context: tuple[str, ...] = (),
) -> tuple[TaskBatch, ...]:
    """Plan independent ideation, adversarial review, and synthesis stages."""
    if not isinstance(focus, str) or not focus.strip():
        raise ValueError("focus is required")
    focus = focus.strip()
    if len(focus) > _MAX_FOCUS_CHARS:
        raise ValueError("focus exceeds 4000 characters")
    if not isinstance(context, tuple):
        raise ValueError("context must be a tuple of strings")
    if any(not isinstance(item, str) for item in context):
        raise ValueError("context items must be strings")
    clean_context = tuple(
        item.strip()[:_MAX_CONTEXT_CHARS]
        for item in context
        if item.strip()
    )[:_MAX_CONTEXT_ITEMS]
    context_text = "\n".join(f"- {item}" for item in clean_context)
    context_block = f"\nContext:\n{context_text}" if context_text else ""

    ideate = AgentTask(
        task_id="idea-workflow-ideate",
        role=AgentRole.IDEA,
        instruction=(
            "Generate at least three materially different hypotheses, including "
            "one unconventional approach. State assumptions and expected benefits. "
            "Do not implement, execute, access external systems, merge, or deploy. "
            f"Focus: {focus}{context_block}"
        ),
        resources=frozenset({"idea-workflow:ideation"}),
        priority=3,
    )
    critique = AgentTask(
        task_id="idea-workflow-critique",
        role=AgentRole.REVIEWER,
        instruction=(
            "Independently challenge the proposed hypotheses. Identify falsifiable "
            "claims, counterexamples, feasibility constraints, failure modes, and "
            "missing evidence. Do not silently discard unconventional ideas. "
            "Do not implement, execute, merge, or deploy."
        ),
        resources=frozenset({"idea-workflow:critique"}),
        depends_on=(ideate.task_id,),
        priority=2,
    )
    synthesize = AgentTask(
        task_id="idea-workflow-synthesize",
        role=AgentRole.INTEGRATOR,
        instruction=(
            "Synthesize the hypotheses and critique into a ranked research brief. "
            "Preserve useful disagreement; specify the smallest reversible "
            "experiment, success/failure criteria, required evidence, and human "
            "approval boundary. Do not implement, execute, merge, or deploy."
        ),
        resources=frozenset({"idea-workflow:synthesis"}),
        depends_on=(critique.task_id,),
        priority=1,
    )
    return plan_batches((ideate, critique, synthesize))


__all__ = ["build_idea_workflow"]
