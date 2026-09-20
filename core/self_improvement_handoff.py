"""Immutable handoff contract for approved self-improvement tasks.

This module converts an already-approved ControlTower decision into a bounded
handoff object. It never executes a task, mutates the repository, or grants
additional permissions.
"""
from __future__ import annotations

from dataclasses import dataclass

from .control_tower import ControlTowerDecision
from .multi_agent import AgentRole, AgentTask
from .self_improvement_policy import SelfImprovementDecision, assess_self_improvement


@dataclass(frozen=True)
class ApprovedImprovementHandoff:
    """The exact task approved for a bounded downstream pipeline."""

    task: AgentTask
    task_hash: str
    allowed_paths: tuple[str, ...]


def build_approved_improvement_handoff(
    decision: ControlTowerDecision,
    allowed_paths: tuple[str, ...],
) -> ApprovedImprovementHandoff:
    """Build a handoff only when approval, task identity, and path policy all hold."""
    if not isinstance(decision, ControlTowerDecision):
        raise TypeError("decision must be a ControlTowerDecision")

    normalized_paths = tuple(dict.fromkeys(str(path).strip() for path in allowed_paths if str(path).strip()))
    if not normalized_paths:
        raise ValueError("allowed_paths are required")

    assessment = assess_self_improvement(normalized_paths)
    if assessment.decision is not SelfImprovementDecision.AUTONOMOUS_REVIEW:
        raise PermissionError(f"self-improvement target policy: {assessment.decision.value}")

    if not decision.approved_for_pipeline:
        raise PermissionError("self-improvement proposal is not approved for pipeline")

    task = decision.approved_task
    if task is None:
        raise PermissionError("approved task is unavailable")
    if not decision.approved_task_matches(task):
        raise PermissionError("approved task identity does not match")

    if task.role is not AgentRole.DEBUGGER:
        raise PermissionError("only bounded debugger tasks may enter self-improvement handoff")

    return ApprovedImprovementHandoff(
        task=task,
        task_hash=decision.approved_task_hash or "",
        allowed_paths=tuple(sorted(normalized_paths)),
    )


__all__ = [
    "ApprovedImprovementHandoff",
    "build_approved_improvement_handoff",
]
