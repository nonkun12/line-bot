"""Composed, read-only self-improvement cycle.

This module connects persisted runtime signals to deterministic analysis and
reviewable proposals. It never edits files, executes proposals, merges, or
deploys.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from .control_tower import ControlTower, ControlTowerDecision

from .agent_runtime import RuntimeReport
from .self_improvement import ImprovementProposal, ImprovementSignal, SelfImprovementEngine
from .self_improvement_analyzer import ImprovementAnalysis, analyze_signals
from .self_improvement_history import SelfImprovementHistory
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
    """Persist one report's signals and produce bounded reviewable proposals."""
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

    # A generated proposal is inert. When a ControlTower is supplied, every
    # proposal must pass its Creator/Critic gate before it is exposed as
    # approved for downstream execution.
    decisions: list["ControlTowerDecision"] = []
    approved: list[ImprovementProposal] = []
    if control_tower is not None:
        for proposal in proposals:
            decision = control_tower.evaluate_proposal(report, proposal)
            decisions.append(decision)
            if decision.approved_for_pipeline:
                approved.append(proposal)

    return SelfImprovementCycleResult(
        new_signals=new_signals,
        all_signals=all_signals,
        analysis=analysis,
        proposals=proposals,
        approved_proposals=tuple(approved),
        control_tower_decisions=tuple(decisions),
    )


__all__ = ["SelfImprovementCycleResult", "run_self_improvement_cycle"]
