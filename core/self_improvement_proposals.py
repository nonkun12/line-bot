"""Deterministic, safety-bounded proposal generation for self-improvement.

This module converts recurring analysis patterns into reviewable proposals only.
It never edits files, invokes a model, merges, or deploys.
"""
from __future__ import annotations

from .multi_agent import AgentRole, AgentTask
from .self_improvement import ImprovementProposal, ImprovementSignal
from .self_improvement_analyzer import ImprovementAnalysis, ImprovementPattern
from .self_improvement_policy import SelfImprovementDecision, assess_self_improvement


def generate_improvement_proposals(
    analysis: ImprovementAnalysis,
    signals: tuple[ImprovementSignal, ...] = (),
    *,
    target_paths: tuple[str, ...] = (),
    max_proposals: int = 3,
) -> tuple[ImprovementProposal, ...]:
    """Generate bounded proposals from recurring patterns.

    Protected paths require explicit approval and therefore produce no
    autonomous proposal. Non-recurring analyses produce no proposals.
    """
    if max_proposals < 1:
        raise ValueError("max_proposals must be >= 1")
    if not analysis.has_recurring_pattern:
        return ()

    assessment = assess_self_improvement(target_paths)
    if assessment.decision is not SelfImprovementDecision.AUTONOMOUS_REVIEW:
        return ()

    signal_by_id = {id(signal): signal for signal in signals}
    proposals: list[ImprovementProposal] = []
    for pattern in analysis.recurring_patterns[:max_proposals]:
        matched = tuple(
            signal
            for signal in signals
            if signal.kind in {"failure", "repair"}
            and _matches_pattern(signal, pattern)
        )
        if not matched:
            matched = tuple(signals[-pattern.count:]) if signals else ()
        task_id = f"self-improvement:pattern:{pattern.key[:80]}"
        task = AgentTask(
            task_id=task_id,
            role=AgentRole.DEBUGGER,
            instruction=(
                "Investigate this recurring autonomous-development failure pattern, "
                "add or update a regression test, and propose the smallest safe fix. "
                "Do not modify protected configuration, secrets, workflows, or "
                "self-improvement control files."
            ),
            resources=frozenset(pattern.task_ids or {"runtime"}),
            priority=10,
        )
        proposals.append(
            ImprovementProposal(
                title=f"Investigate recurring failure: {pattern.key[:100]}",
                rationale=(
                    f"Observed {pattern.count} occurrences of the same normalized "
                    "failure pattern. Reproduce it and add a regression test before "
                    "changing behavior."
                ),
                signals=matched,
                task=task,
            )
        )
    return tuple(proposals)


def _matches_pattern(signal: ImprovementSignal, pattern: ImprovementPattern) -> bool:
    detail = " ".join(str(signal.detail).lower().split())
    return pattern.key in detail or _normalize_for_match(detail) == pattern.key


def _normalize_for_match(detail: str) -> str:
    import re

    return re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", detail).strip()


__all__ = ["generate_improvement_proposals"]
