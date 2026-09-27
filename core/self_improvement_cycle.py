"""Composed, read-only self-improvement cycle.

This module connects persisted runtime signals to deterministic analysis and
reviewable proposals. It never edits files, executes proposals, merges, or
deploys.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .control_tower import ControlTower, ControlTowerDecision

from .agent_runtime import RuntimeReport
from .self_improvement import ImprovementProposal, ImprovementSignal, SelfImprovementEngine
from .self_improvement_analyzer import ImprovementAnalysis, analyze_signals
from .self_improvement_history import SelfImprovementHistory, SelfImprovementMemoryRecord
from .self_improvement_proposals import generate_improvement_proposals


@dataclass(frozen=True)
class SelfImprovementCycleResult:
    """Immutable output of one bounded self-improvement cycle."""

    new_signals: tuple[ImprovementSignal, ...]
    all_signals: tuple[ImprovementSignal, ...]
    analysis: ImprovementAnalysis
    proposals: tuple[ImprovementProposal, ...]
    approved_proposals: tuple[ImprovementProposal, ...]
    control_tower_decisions: tuple["ControlTowerDecision", ...]


def run_self_improvement_cycle(
    report: RuntimeReport,
    history_path: str | Path,
    *,
    target_paths: tuple[str, ...] = (),
    control_tower: "ControlTower | None" = None,
    max_history: int = 200,
    min_occurrences: int = 2,
    max_patterns: int = 5,
    max_proposals: int = 3,
) -> SelfImprovementCycleResult:
    """Persist one report and one bounded outcome/cause/improvement memory entry."""
    if not isinstance(report, RuntimeReport):
        raise TypeError("report must be a RuntimeReport")

    history = SelfImprovementHistory(history_path, max_records=max_history)
    previous = history.load()
    engine = SelfImprovementEngine(max_signals=max_history)
    new_signals = engine.observe(report)

    if new_signals:
        history.append(new_signals)

    all_signals = previous + new_signals
    analysis = analyze_signals(
        all_signals,
        min_occurrences=min_occurrences,
        max_patterns=max_patterns,
    )
    proposals = generate_improvement_proposals(
        analysis,
        all_signals,
        target_paths=target_paths,
        max_proposals=max_proposals,
    )

    decisions: list["ControlTowerDecision"] = []
    approved: list[ImprovementProposal] = []
    if control_tower is not None:
        for proposal in proposals:
            decision = control_tower.evaluate_proposal(report, proposal)
            decisions.append(decision)
            if decision.approved_for_pipeline and decision.approved_task_matches(proposal.task):
                approved.append(proposal)

    outcome = "PASS" if report.success and report.integration_ready else "FAIL"
    if report.error and "blocked" in report.error.casefold():
        outcome = "BLOCKED"
    cause = (report.error or report.failed_task_id or "development gate passed")[:1200]
    improvements = tuple(
        f"{proposal.title}: {proposal.rationale}"[:1200]
        for proposal in proposals[:3]
    )
    if approved:
        next_action = "review approved self-improvement handoff before execution"
    elif proposals:
        next_action = "review generated self-improvement proposal before execution"
    else:
        next_action = "carry validated outcome into the next bounded development loop"
    memory = SelfImprovementMemoryRecord(
        outcome=outcome,
        cause=cause,
        improvements=improvements,
        next_action=next_action,
        target_path=", ".join(target_paths)[:1200],
        recurring_patterns=tuple(pattern.key[:1200] for pattern in analysis.recurring_patterns[:5]),
    )
    history.append_memory(memory)

    return SelfImprovementCycleResult(
        new_signals=new_signals,
        all_signals=all_signals,
        analysis=analysis,
        proposals=proposals,
        approved_proposals=tuple(approved),
        control_tower_decisions=tuple(decisions),
    )


__all__ = ["SelfImprovementCycleResult", "run_self_improvement_cycle"]
