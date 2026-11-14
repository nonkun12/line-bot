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
    cause = (
        "development gate passed" if outcome == "PASS"
        else "development cycle blocked" if outcome == "BLOCKED"
        else "development cycle failed"
    )
    improvements = tuple(
        "review recurring development failure" for _ in proposals[:3]
    ) or (
        ("retain verified outcome for next cycle",) if outcome == "PASS"
        else ("resolve safety or evidence block before retry",) if outcome == "BLOCKED"
        else ("review recurring development failure",) if outcome == "FAIL"
        else ()
    )
    if approved:
        next_action = "review failure evidence before another attempt"
    elif proposals:
        next_action = "review failure evidence before another attempt"
    else:
        next_action = "continue bounded development loop after review"
    memory = SelfImprovementMemoryRecord(
        outcome=outcome,
        cause=cause,
        improvements=improvements,
        next_action=next_action,
        target_path="",
        recurring_patterns=tuple(pattern.key for pattern in analysis.recurring_patterns[:5] if pattern.key in {"task passed or verified no-change", "development required repair attempts", "development failure observed", "development failure observed: pytest", "development failure observed: timeout", "development failure observed: import", "development failure observed: assertion", "development failure observed: blocked", "development failure observed: runtime"}),
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
