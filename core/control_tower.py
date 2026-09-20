"""Bounded management layer for autonomous development improvement.

Control Tower observes runtime outcomes, asks the existing self-improvement
engine for one reviewable proposal, and optionally runs that proposal through
the real-model Creator/Critic pair. It never applies model output directly.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .agent_runtime import RuntimeReport
from .creator_critic import DuelResult, CreatorCriticLoop
from .multi_agent import AgentTask
from .self_improvement import ImprovementProposal, ImprovementSignal, SelfImprovementEngine


@dataclass(frozen=True)
class ControlTowerDecision:
    """One bounded management decision; application remains downstream."""

    signals: tuple[ImprovementSignal, ...]
    proposal: ImprovementProposal | None
    duel: tuple[DuelResult, ...] = ()
    approved_task_hash: str | None = None

    @property
    def approved_for_pipeline(self) -> bool:
        return bool(self.duel and self.duel[-1].evaluation.passed)

    @property
    def approved_task(self) -> AgentTask | None:
        """Return the proposal task only after an explicit Creator/Critic pass."""
        if not self.approved_for_pipeline or self.proposal is None or self.approved_task_hash is None:
            return None
        task = self.proposal.task
        if task is None or _task_hash(task) != self.approved_task_hash:
            return None
        return task

    def approved_task_matches(self, task: AgentTask | None) -> bool:
        """Verify that the exact task approved by the Creator/Critic is being used."""
        return task is not None and self.approved_for_pipeline and self.approved_task_hash == _task_hash(task)


class ControlTower:
    """Coordinate runtime feedback and bounded Creator/Critic evaluation."""

    def __init__(
        self,
        feedback_engine: SelfImprovementEngine | None = None,
        creator_critic: CreatorCriticLoop | None = None,
    ) -> None:
        self.feedback_engine = feedback_engine or SelfImprovementEngine()
        self.creator_critic = creator_critic

    def evaluate_proposal(
        self,
        report: RuntimeReport,
        proposal: ImprovementProposal,
        *,
        objective: str | None = None,
        evidence: Mapping[str, object] | None = None,
    ) -> ControlTowerDecision:
        """Evaluate an already-generated proposal without granting execution rights.

        The proposal remains inert until the Creator/Critic gate passes. If no
        reviewer is configured, evaluation fails closed and no task is exposed.
        """
        if not isinstance(proposal, ImprovementProposal):
            raise TypeError("proposal must be an ImprovementProposal")
        if self.creator_critic is None:
            return ControlTowerDecision((), proposal)

        target = (objective or proposal.title).strip()
        if not target:
            return ControlTowerDecision((), proposal)

        measured = _report_evidence(report, evidence)

        def evidence_provider(_candidate: object) -> Mapping[str, object]:
            return measured

        task_hash = task_hash_for_task(proposal.task)
        if task_hash is None:
            return ControlTowerDecision((), proposal)
        measured["approved_task_hash"] = task_hash
        duel = self.creator_critic.run(target, evidence_provider)
        return ControlTowerDecision((), proposal, duel, task_hash)

    def observe(
        self,
        report: RuntimeReport,
        *,
        objective: str | None = None,
        evidence: Mapping[str, object] | None = None,
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

        measured = _report_evidence(report, evidence)

        def evidence_provider(_candidate: object) -> Mapping[str, object]:
            return measured

        task_hash = task_hash_for_task(proposal.task)
        if task_hash is None:
            return ControlTowerDecision(signals, proposal)
        measured["approved_task_hash"] = task_hash
        duel = self.creator_critic.run(target, evidence_provider)
        return ControlTowerDecision(signals, proposal, duel, task_hash)


def task_hash(task: AgentTask | None) -> str | None:
    if task is None:
        return None
    payload = {
        "task_id": task.task_id,
        "role": task.role.value,
        "instruction": task.instruction,
        "resources": sorted(task.resources),
        "depends_on": list(task.depends_on),
        "priority": task.priority,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# Backward-compatible internal alias while callers migrate to the public helper.
task_hash_for_task = task_hash
_task_hash = task_hash


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


__all__ = ["ControlTower", "ControlTowerDecision", "task_hash"]
