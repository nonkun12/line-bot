"""Bounded management layer for autonomous development improvement.

Control Tower observes runtime outcomes, asks the existing self-improvement
engine for one reviewable proposal, and optionally runs that proposal through
the real-model Creator/Critic pair. It never applies model output directly.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Mapping

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
    review_error: str | None = None

    @property
    def approved_for_pipeline(self) -> bool:
        return bool(self.duel and self.duel[-1].evaluation.passed)

    @property
    def approved_task(self) -> AgentTask | None:
        """Return the proposal task only after an explicit Creator/Critic pass."""
        if not self.approved_for_pipeline or self.proposal is None or self.approved_task_hash is None:
            return None
        task = self.proposal.task
        if task is None or task_hash(task) != self.approved_task_hash:
            return None
        return task

    def approved_task_matches(self, task: AgentTask | None) -> bool:
        """Verify that the exact task approved by the Creator/Critic is being used."""
        return task is not None and self.approved_for_pipeline and self.approved_task_hash == task_hash(task)


class ControlTower:
    """Coordinate runtime feedback and bounded Creator/Critic evaluation."""

    def __init__(
        self,
        feedback_engine: SelfImprovementEngine | None = None,
        creator_critic: CreatorCriticLoop | None = None,
        event_recorder: Callable[[object], bool] | None = None,
    ) -> None:
        self.feedback_engine = feedback_engine or SelfImprovementEngine()
        self.creator_critic = creator_critic
        self.event_recorder = event_recorder
        self.last_event_recording_error: str | None = None

    def _record_runtime_observation(self, report: RuntimeReport) -> None:
        """Append bounded runtime evidence without granting execution authority."""
        self.last_event_recording_error = None
        try:
            from .agent_events import AgentEvent, record_agent_event
            recorder = self.event_recorder or record_agent_event
            items = [(item.task.task_id, item.task.role.value, item.result.success, len(item.result.changed_resources)) for item in report.completed]
            if report.failed_task_id:
                items.append((report.failed_task_id, "unknown", False, 0))
            if not items:
                synthetic = "control-tower-" + hashlib.sha256(json.dumps({"success": report.success, "rounds": report.rounds, "repair_attempts": report.repair_attempts, "integration_ready": report.integration_ready}, sort_keys=True).encode("utf-8")).hexdigest()[:24]
                items.append((synthetic, "control_tower", report.success, 0))
            for task_id, role, success, changed_count in items:
                digest = hashlib.sha256(f"{task_id}|{role}|{success}|{report.rounds}|{report.repair_attempts}".encode("utf-8")).hexdigest()
                recorder(AgentEvent(event_id="runtime-" + digest, task_id=task_id, agent_id="control_tower", role=role, event_type="runtime_observed", status="COMPLETED" if success else "FAILED", payload={"runtime_success": report.success, "integration_ready": report.integration_ready, "rounds": report.rounds, "repair_attempts": report.repair_attempts, "changed_resource_count": changed_count}))
        except Exception as exc:
            self.last_event_recording_error = type(exc).__name__

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

        approved_hash = task_hash(proposal.task)
        if approved_hash is None:
            return ControlTowerDecision((), proposal)
        measured["approved_task_hash"] = approved_hash
        try:
            duel = self.creator_critic.run(target, evidence_provider)
        except Exception as exc:
            # A provider/rate-limit failure must not erase the local observation.
            # Record only the exception class; raw provider text may contain sensitive data.
            return ControlTowerDecision((), proposal, review_error=type(exc).__name__)
        return ControlTowerDecision((), proposal, duel, approved_hash)

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
        self._record_runtime_observation(report)
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

        approved_hash = task_hash(proposal.task)
        if approved_hash is None:
            return ControlTowerDecision(signals, proposal)
        measured["approved_task_hash"] = approved_hash
        try:
            duel = self.creator_critic.run(target, evidence_provider)
        except Exception as exc:
            # Fail closed on review failure while preserving the observed signals/proposal.
            return ControlTowerDecision(signals, proposal, review_error=type(exc).__name__)
        return ControlTowerDecision(signals, proposal, duel, approved_hash)


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
        # Explicit evidence may refine business metrics, but cannot override
        # runtime-derived safety/control facts.
        protected = {"safety", "runtime_success", "integration_ready", "rounds", "repair_attempts"}
        measured.update({key: value for key, value in dict(extra).items() if key not in protected})
    return measured


__all__ = ["ControlTower", "ControlTowerDecision", "task_hash"]
