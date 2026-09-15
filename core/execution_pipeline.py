"""Generic execution pipeline for the universal AI Agent platform.

The pipeline is intentionally side-effect free at this stage.  It produces a
validated execution plan that later adapters can execute against GitHub,
artifact storage, deployment systems, or other providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .task_routing import ProjectResolver, ResolvedTarget, TaskClassification, TaskClassifier, TaskMode


@dataclass(frozen=True)
class WorkRequest:
    user_id: str
    message: str
    channel: str = "line"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkPlan:
    mode: TaskMode
    classification: TaskClassification
    target: ResolvedTarget
    stages: tuple[str, ...]
    requires_approval: bool = False


class Planner(Protocol):
    def plan(self, request: WorkRequest, classification: TaskClassification, target: ResolvedTarget) -> WorkPlan:
        ...


class DefaultPlanner:
    """Select the smallest safe stage set for each governed task mode."""

    def plan(self, request: WorkRequest, classification: TaskClassification, target: ResolvedTarget) -> WorkPlan:
        if not target.safe:
            return WorkPlan(classification.mode, classification, target, ("reject",), requires_approval=False)

        stages_by_mode = {
            TaskMode.SELF_IMPROVEMENT: (
                "inspect", "plan", "implement", "test", "review", "repair_if_needed",
                "integrate", "pull_request", "merge_gate", "deploy_gate", "verify", "report",
            ),
            TaskMode.NEW_SOFTWARE: (
                "requirements", "classify_project", "name_repository", "create_repository",
                "architect", "implement", "qa", "review", "repair_if_needed", "integrate",
                "pull_request", "merge_gate", "deploy", "verify", "report",
            ),
            TaskMode.EXISTING_SOFTWARE: (
                "inspect", "plan", "implement", "test", "review", "repair_if_needed",
                "integrate", "pull_request", "merge_gate", "deploy_gate", "verify", "report",
            ),
            TaskMode.AGENT_MANAGEMENT: (
                "requirements", "generate", "validate", "test", "review", "enable", "report",
            ),
            TaskMode.NON_SOFTWARE: (
                "requirements", "research_or_process", "validate", "review", "artifact", "report",
            ),
            TaskMode.NORMAL: ("respond",),
        }
        stages = stages_by_mode.get(classification.mode, ("reject",))
        return WorkPlan(
            classification.mode,
            classification,
            target,
            stages,
            requires_approval=classification.mode in {TaskMode.NEW_SOFTWARE, TaskMode.AGENT_MANAGEMENT},
        )


@dataclass(frozen=True)
class ExecutionResult:
    request: WorkRequest
    plan: WorkPlan


class Manager:
    """Coordinate Manager -> Classifier -> Resolver -> Planner."""

    def __init__(
        self,
        classifier: TaskClassifier | None = None,
        resolver: ProjectResolver | None = None,
        planner: Planner | None = None,
    ) -> None:
        self.classifier = classifier or TaskClassifier()
        self.resolver = resolver or ProjectResolver()
        self.planner = planner or DefaultPlanner()

    def prepare(self, request: WorkRequest) -> ExecutionResult:
        if not isinstance(request, WorkRequest):
            raise TypeError("request must be a WorkRequest")
        classification = self.classifier.classify(request.message)
        target = self.resolver.resolve(classification)
        plan = self.planner.plan(request, classification, target)
        return ExecutionResult(request=request, plan=plan)


__all__ = [
    "WorkRequest",
    "WorkPlan",
    "Planner",
    "DefaultPlanner",
    "ExecutionResult",
    "Manager",
]
