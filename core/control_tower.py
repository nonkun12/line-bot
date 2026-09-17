"""Bounded management layer for autonomous development improvement.

Control Tower observes runtime outcomes, asks the existing self-improvement
engine for one reviewable proposal, and optionally runs that proposal through
the real-model Creator/Critic pair. It never applies model output directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .agent_runtime import RuntimeReport
from .creator_critic import DuelResult, CreatorCriticLoop, ImprovementCandidate
from .multi_agent import AgentTask
from .self_improvement import ImprovementProposal, ImprovementSignal, SelfImprovementEngine


@dataclass(frozen=True)
class ControlTowerDecision:
    """One bounded management decision; application remains downstream."""

    signals: tuple[ImprovementSignal, ...]
    proposal: ImprovementProposal | None
    duel: tuple[DuelResult, ...] = ()
    evaluation_error: str | None = None

    @property
    def approved_for_pipeline(self) -> bool:
        return bool(self.duel and self.duel[-1].evaluation.passed)

    @property
    def approved_task(self) -> AgentTask | None:
        """Return the proposal task only after an explicit Creator/Critic pass."""
        if not self.approved_for_pipeline or self.proposal is None:
            return None
        return self.proposal.task


class ControlTower:
    """Coordinate runtime feedback and bounded Creator/Critic evaluation."""

    def __init__(
        self,
        feedback_engine: SelfImprovementEngine | None = None,
        creator_critic: CreatorCriticLoop | None = None,
    ) -> None:
        self.feedback_engine = feedback_engine or SelfImprovementEngine()
        self.creator_critic = creator_critic

    def observe(
        self,
        report: RuntimeReport,
        *,
        objective: str | None = None,
        evidence: Mapping[str, object] | None = None,
        candidate_evidence_provider: Callable[[ImprovementCandidate], Mapping[str, object]] | None = None,
    ) -> ControlTowerDecision:
        """Observe one report and optionally evaluate a generated improvement.

        Evidence is explicit and deterministic; model text cannot manufacture
        safety or test results. No repository mutation occurs in this method.
        """
        signals = self.feedback_engine.observe(report)
        proposal = self.feedback_engine.propose()
        if proposal is None or self.creator_critic is None:
            return ControlTowerDecision(signals, proposal)

        target = (objective or proposal.title).strip()
        if not target:
            return ControlTowerDecision(signals, proposal)

        if candidate_evidence_provider is None:
            # Never treat the original runtime report as fresh evidence for a new candidate.
            return ControlTowerDecision(signals, proposal)

        baseline = _report_evidence(report, evidence)

        def evidence_provider(candidate: ImprovementCandidate) -> Mapping[str, object]:
            fresh = candidate_evidence_provider(candidate)
            if not isinstance(fresh, Mapping):
                raise TypeError("candidate evidence provider must return a mapping")
            measured = dict(baseline)
            measured.update(dict(fresh))
            measured["candidate_id"] = candidate.candidate_id
            measured["candidate_evaluated"] = True
            return measured

        try:
            duel = self.creator_critic.run(target, evidence_provider)
        except Exception as exc:
            # Candidate evaluation is an advisory gate; provider failures never approve work.
            return ControlTowerDecision(
                signals,
                proposal,
                evaluation_error=f"{type(exc).__name__}: {exc}",
            )
        return ControlTowerDecision(signals, proposal, duel)


def _report_evidence(
    report: RuntimeReport,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Derive fail-closed metrics from runtime facts, then add explicit evidence."""
    success = report.success and report.integration_ready
    rounds = max(1, report.rounds)
    repair_penalty = min(0.3, report.repair_attempts * 0.1)
    measured: dict[str, object] = {
        "accuracy": 1.0 if success else 0.0,
        "stability": max(0.0, (1.0 if success else 0.0) - repair_penalty),
        "efficiency": max(0.0, 1.0 - ((rounds - 1) * 0.15) - repair_penalty),
        "safety": 1.0 if success else 0.0,
        "runtime_success": report.success,
        "integration_ready": report.integration_ready,
        "rounds": report.rounds,
        "repair_attempts": report.repair_attempts,
    }
    if extra:
        measured.update(dict(extra))
    return measured


__all__ = ["ControlTower", "ControlTowerDecision"]
