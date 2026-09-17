"""Distributed, read-only analysis stage for bounded self-improvement.

The stage uses real-model agents to analyze a completed runtime report before
Creator/Critic evaluation. It never applies proposals, writes files, mutates git,
or treats model output as execution evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .agent_runtime import RuntimeReport
from .control_tower import ControlTower, ControlTowerDecision
from .distributed_executor import DistributedAIExecutor
from .creator_critic import ImprovementCandidate
from .distributed_scheduler import DistributedTaskScheduler
from .multi_agent import AgentResult, AgentRole, AgentTask


@dataclass(frozen=True)
class DistributedSelfImprovementResult:
    """Bounded AI analysis plus an optional management decision."""

    analysis_results: tuple[AgentResult, ...]
    analysis_success: bool
    evidence: Mapping[str, object]
    decision: ControlTowerDecision | None = None


class DistributedSelfImprovementLoop:
    """Run read-only specialist analysis, then hand evidence to Control Tower."""

    def __init__(
        self,
        *,
        executor: DistributedAIExecutor | None = None,
        control_tower: ControlTower | None = None,
        max_workers: int = 1,
        isolated: bool = False,
        candidate_evidence_provider: Callable[[ImprovementCandidate], Mapping[str, object]] | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_workers > 1 and not isolated:
            raise ValueError("max_workers > 1 requires explicit isolated=True")
        self._executor = executor or DistributedAIExecutor(
            allowed_roles={
                AgentRole.MANAGER: True,
                AgentRole.DEBUGGER: True,
                AgentRole.REVIEWER: True,
            }
        )
        self._scheduler = DistributedTaskScheduler(
            {
                AgentRole.MANAGER: self._executor,
                AgentRole.DEBUGGER: self._executor,
                AgentRole.REVIEWER: self._executor,
            },
            max_workers=max_workers,
        )
        self._control_tower = control_tower
        self._candidate_evidence_provider = candidate_evidence_provider

    @property
    def max_workers(self) -> int:
        return self._scheduler.max_workers

    def run(
        self,
        report: RuntimeReport,
        *,
        objective: str | None = None,
        evidence: Mapping[str, object] | None = None,
    ) -> DistributedSelfImprovementResult:
        """Analyze one failed/repairing runtime result and optionally evaluate it.

        Model-generated analysis is advisory only. The original runtime facts remain
        the source of truth for safety and integration status.
        """
        if report.failed_task_id is None and report.error is None:
            return DistributedSelfImprovementResult((), True, dict(evidence or {}), None)

        target = (objective or "improve the latest autonomous-development outcome").strip()
        failure = (report.error or "runtime failure without error detail").strip()[:2000]
        failed_task = (report.failed_task_id or "unknown").strip()[:200]
        manager_id = "self-improvement:manager"
        debugger_id = "self-improvement:debugger"
        reviewer_id = "self-improvement:reviewer"

        manager_task = AgentTask(
            manager_id,
            AgentRole.MANAGER,
            (
                f"Prioritize one bounded improvement objective for: {target}. "
                f"Failed task: {failed_task}. Runtime error: {failure}. "
                "Return only a concise analysis summary and investigation priorities."
            ),
            resources=frozenset({"self-improvement:management"}),
        )

        try:
            manager_run = self._scheduler.run((manager_task,))
        except Exception as exc:
            return DistributedSelfImprovementResult(
                (),
                False,
                {
                    "analysis_success": False,
                    "analysis_error": f"{type(exc).__name__}: {exc}",
                    **dict(evidence or {}),
                },
                None,
            )
        manager_results = tuple(manager_run.results)
        if not manager_run.success:
            return DistributedSelfImprovementResult(
                manager_results,
                False,
                {
                    "analysis_success": False,
                    "analysis_agent_count": len(manager_results),
                    "analysis:manager:success": False,
                    "analysis:manager:summary": manager_results[-1].summary[:2000] if manager_results else "",
                    **dict(evidence or {}),
                },
                None,
            )

        manager_summary = manager_results[-1].summary[:2000]
        debugger_task = AgentTask(
            debugger_id,
            AgentRole.DEBUGGER,
            (
                f"Analyze the root cause of failed task {failed_task}. "
                f"Runtime error: {failure}. "
                f"Manager analysis: {manager_summary}. "
                "Identify one reproducible cause and the smallest test-backed "
                "corrective direction. Do not modify files."
            ),
            resources=frozenset({f"runtime:{failed_task}"}),
            depends_on=(manager_task.task_id,),
            priority=10,
        )
        try:
            debugger_run = self._scheduler.run((debugger_task,))
        except Exception as exc:
            return DistributedSelfImprovementResult(
                manager_results,
                False,
                {
                    "analysis_success": False,
                    "analysis_agent_count": len(manager_results),
                    "analysis_error": f"{type(exc).__name__}: {exc}",
                    "analysis:manager:summary": manager_summary,
                    **dict(evidence or {}),
                },
                None,
            )
        debugger_results = tuple(debugger_run.results)
        analysis_results = manager_results + debugger_results
        if not debugger_run.success:
            return DistributedSelfImprovementResult(
                analysis_results,
                False,
                {
                    "analysis_success": False,
                    "analysis_agent_count": len(analysis_results),
                    "analysis:manager:summary": manager_summary,
                    "analysis:debugger:success": False,
                    "analysis:debugger:summary": debugger_results[-1].summary[:2000] if debugger_results else "",
                    **dict(evidence or {}),
                },
                None,
            )

        debugger_summary = debugger_results[-1].summary[:2000]
        reviewer_task = AgentTask(
            reviewer_id,
            AgentRole.REVIEWER,
            (
                f"Review the investigation for objective {target}. "
                f"Manager analysis: {manager_summary}. "
                f"Debugger analysis: {debugger_summary}. "
                "Check safety, scope, testability, and whether the next step "
                "could accidentally grant mutation/tool capabilities. "
                "Return a concise independent review."
            ),
            resources=frozenset({"self-improvement:safety"}),
            depends_on=(manager_task.task_id, debugger_task.task_id),
        )
        try:
            reviewer_run = self._scheduler.run((reviewer_task,))
        except Exception as exc:
            return DistributedSelfImprovementResult(
                analysis_results,
                False,
                {
                    "analysis_success": False,
                    "analysis_agent_count": len(analysis_results),
                    "analysis_error": f"{type(exc).__name__}: {exc}",
                    "analysis:manager:summary": manager_summary,
                    "analysis:debugger:summary": debugger_summary,
                    **dict(evidence or {}),
                },
                None,
            )
        reviewer_results = tuple(reviewer_run.results)
        analysis_results = analysis_results + reviewer_results
        analysis_success = reviewer_run.success

        analysis_evidence: dict[str, object] = {
            "analysis_success": analysis_success,
            "analysis_agent_count": len(analysis_results),
        }
        for result in analysis_results:
            analysis_evidence[f"analysis:{result.task_id}:success"] = result.success
            analysis_evidence[f"analysis:{result.task_id}:summary"] = result.summary[:2000]
        analysis_evidence.update(dict(evidence or {}))

        decision = None
        if analysis_success and self._control_tower is not None:
            decision = self._control_tower.observe(
                report,
                objective=target,
                evidence=analysis_evidence,
                candidate_evidence_provider=self._candidate_evidence_provider,
            )

        return DistributedSelfImprovementResult(
            analysis_results,
            analysis_success,
            analysis_evidence,
            decision,
        )


__all__ = ["DistributedSelfImprovementLoop", "DistributedSelfImprovementResult"]
