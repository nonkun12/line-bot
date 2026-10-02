"""Idea-to-development handoff contract.

IDEA creates proposals; this adapter creates a gated development task only after
an explicit acceptance decision. It never executes the task itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from .idea_ai import Idea
from .multi_agent import AgentRole, AgentTask


@dataclass(frozen=True)
class IdeaAcceptance:
    accepted: bool
    reason: str = ""


def handoff_idea(idea: Idea, acceptance: IdeaAcceptance) -> AgentTask | None:
    if not acceptance.accepted:
        return None
    return AgentTask(
        task_id=f"develop-from-{idea.idea_id}",
        role=AgentRole.IMPLEMENTER,
        instruction=(
            "Implement an accepted IDEA proposal only after normal safety/test gates. "
            f"Proposal: {idea.title}. Rationale: {idea.rationale}. "
            f"Next step: {idea.next_step}. Acceptance: {acceptance.reason}"
        ),
        resources=frozenset({"idea-proposals"}),
        priority=1,
    )
