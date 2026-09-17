"""Unified management AI for bounded distributed specialist execution.

The manager plans work, validates model output, dispatches dependency-safe tasks,
and collects results. Planning text never grants tools or repository mutation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence

from ai_client import generate_chat_completion

from .agent_communication import AgentMessage, AgentMessageBus
from .distributed_scheduler import DistributedRun, DistributedTaskScheduler
from .management_contract import ManagementDecision, ManagementRequest
from .management_router import route
from .multi_agent import AgentRole, AgentTask, TaskBatch, plan_batches


ModelCall = Callable[[str], str]

PLANNABLE_ROLES = frozenset(
    {
        AgentRole.GENERAL,
        AgentRole.VOICE,
        AgentRole.ENGLISH,
        AgentRole.NEWS,
        AgentRole.STOCKS,
        AgentRole.JOBS,
    }
)

BLOCKED_TERMS = (
    "rm ",
    "git ",
    "deploy",
    "credential",
    "password",
    "secret",
    ".env",
    "shell command",
    "production mutation",
)


class ManagementPlanningError(ValueError):
    """Raised when the management model returns an invalid or unsafe plan."""


@dataclass(frozen=True)
class ManagementPlan:
    objective: str
    decision: ManagementDecision
    tasks: tuple[AgentTask, ...]
    parallel_safe: bool = False

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise ValueError("objective is required")
        if not self.tasks:
            raise ValueError("at least one task is required")
        if len(self.tasks) > 6:
            raise ValueError("management plan cannot contain more than 6 tasks")


@dataclass(frozen=True)
class ManagementRun:
    plan: ManagementPlan
    batches: tuple[TaskBatch, ...]
    distributed: DistributedRun

    @property
    def success(self) -> bool:
        return self.distributed.success


class ManagementPlanner(Protocol):
    def plan(self, request: ManagementRequest, decision: ManagementDecision) -> ManagementPlan:
        ...


class ModelManagementPlanner:
    """Turn a user request into a bounded, validated specialist task graph."""

    def __init__(self, *, model_call: ModelCall | None = None, max_tasks: int = 6) -> None:
        if max_tasks < 1 or max_tasks > 6:
            raise ValueError("max_tasks must be between 1 and 6")
        self._model_call = model_call or groq_management_call
        self._max_tasks = max_tasks

    def plan(self, request: ManagementRequest, decision: ManagementDecision) -> ManagementPlan:
        prompt = (
            "You are the MANAGEMENT AI at the top of a distributed specialist system.\n"
            "Break the user request into small specialist tasks. Prefer parallel work "
            "when resources are independent. Use dependencies only for real data flow.\n"
            "Never request secrets, credentials, shell commands, git operations, deployment, "
            "direct production mutation, or tool calls. Return JSON only.\n"
            "Shape: {"
            "\"objective\":\"...\","
            "\"parallel_safe\":true,"
            "\"tasks\":["
            "{\"task_id\":\"...\",\"role\":\"stocks\","
            "\"instruction\":\"...\",\"resources\":[\"market-data\"],"
            "\"depends_on\":[],\"priority\":1}"
            "]}\n"
            "Allowed roles: general, voice, english, news, stocks, jobs.\n"
            f"Primary route: {decision.specialist.value}\n"
            f"User request: {request.message.strip()}\n"
            f"Maximum tasks: {self._max_tasks}"
        )
        return self._validate(_parse_json(self._model_call(prompt)), request, decision)

    def _validate(
        self,
        payload: Mapping[str, object],
        request: ManagementRequest,
        decision: ManagementDecision,
    ) -> ManagementPlan:
        objective = payload.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise ManagementPlanningError("plan objective is required")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ManagementPlanningError("plan tasks are required")
        if len(raw_tasks) > self._max_tasks:
            raise ManagementPlanningError("plan exceeds task limit")

        tasks: list[AgentTask] = []
        seen: set[str] = set()
        for raw in raw_tasks:
            if not isinstance(raw, Mapping):
                raise ManagementPlanningError("each task must be an object")
            task_id = raw.get("task_id")
            role_name = raw.get("role")
            instruction = raw.get("instruction")
            resources = raw.get("resources", [])
            depends_on = raw.get("depends_on", [])
            priority = raw.get("priority", 0)

            if not isinstance(task_id, str) or not task_id.strip():
                raise ManagementPlanningError("task_id is required")
            if task_id in seen:
                raise ManagementPlanningError(f"duplicate task_id: {task_id}")
            seen.add(task_id)

            try:
                role = AgentRole(str(role_name))
            except ValueError as exc:
                raise ManagementPlanningError(f"unsupported role: {role_name!r}") from exc
            if role not in PLANNABLE_ROLES:
                raise ManagementPlanningError(f"role cannot be assigned by management AI: {role.value}")
            if not isinstance(instruction, str) or not instruction.strip():
                raise ManagementPlanningError(f"instruction is required for {task_id}")
            if len(instruction) > 4000:
                raise ManagementPlanningError(f"instruction too long for {task_id}")
            lowered = instruction.casefold()
            if any(term in lowered for term in BLOCKED_TERMS):
                raise ManagementPlanningError(f"unsafe instruction rejected for {task_id}")

            if not isinstance(resources, list) or len(resources) > 8 or any(
                not isinstance(item, str) or not item.strip() for item in resources
            ):
                raise ManagementPlanningError(f"invalid resources for {task_id}")
            if not isinstance(depends_on, list) or any(
                not isinstance(item, str) or not item.strip() for item in depends_on
            ):
                raise ManagementPlanningError(f"invalid dependencies for {task_id}")
            if not isinstance(priority, int) or isinstance(priority, bool):
                raise ManagementPlanningError(f"priority must be an integer for {task_id}")

            tasks.append(
                AgentTask(
                    task_id=task_id.strip(),
                    role=role,
                    instruction=instruction.strip(),
                    resources=frozenset(item.strip() for item in resources),
                    depends_on=tuple(item.strip() for item in depends_on),
                    priority=max(-10, min(10, priority)),
                )
            )

        try:
            batches = plan_batches(tasks)
        except Exception as exc:
            raise ManagementPlanningError(f"invalid task graph: {exc}") from exc

        parallel_safe = bool(payload.get("parallel_safe", False))
        if not any(len(batch.tasks) > 1 for batch in batches):
            parallel_safe = False
        return ManagementPlan(objective.strip(), decision, tuple(tasks), parallel_safe)


class ManagementAI:
    """Manager -> distributed specialists -> result mailbox."""

    def __init__(
        self,
        executors: Mapping[AgentRole, object],
        *,
        planner: ManagementPlanner | None = None,
        message_bus: AgentMessageBus | None = None,
        max_workers: int = 1,
        isolated: bool = False,
    ) -> None:
        if max_workers > 1 and not isolated:
            raise ValueError("parallel management execution requires isolated=True")
        self._executors = dict(executors)
        self._planner = planner or ModelManagementPlanner()
        self._message_bus = message_bus or AgentMessageBus()
        self._max_workers = max_workers

    @property
    def message_bus(self) -> AgentMessageBus:
        return self._message_bus

    def plan(self, request: ManagementRequest) -> ManagementPlan:
        return self._planner.plan(request, route(request))

    def run(self, request: ManagementRequest) -> ManagementRun:
        plan = self.plan(request)
        workers = self._max_workers if plan.parallel_safe else 1
        distributed = DistributedTaskScheduler(self._executors, max_workers=workers).run(plan.tasks)
        batches = plan_batches(plan.tasks)
        for result in distributed.results:
            self._message_bus.send(
                AgentMessage(
                    message_id=f"{result.task_id}:result",
                    sender=result.task_id,
                    recipient="management",
                    message_type="task_result",
                    content=result.summary[:4000],
                    correlation_id=request.user_id,
                    context={
                        "success": result.success,
                        "changed_resources": sorted(result.changed_resources),
                    },
                    safety_constraints=("result-only", "no-permission-grant"),
                )
            )
        return ManagementRun(plan, batches, distributed)


def groq_management_call(prompt: str) -> str:
    """Use the existing AI boundary for planning only."""
    response = generate_chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a planning-only management AI. Return planning data, "
                    "never tool calls or executable operations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1600,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ManagementPlanningError("AI provider returned no choices")
    message = getattr(choices[0], "message", None)
    text = getattr(message, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise ManagementPlanningError("AI provider returned empty content")
    return text.strip()


def _parse_json(raw: str) -> Mapping[str, object]:
    text = raw.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith(fence):
            text = "\n".join(lines[1:-1]) if lines[-1].startswith(fence) else "\n".join(lines[1:])
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManagementPlanningError("management planner did not return valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ManagementPlanningError("management planner must return a JSON object")
    return value


__all__ = [
    "ManagementAI",
    "ManagementPlan",
    "ManagementPlanner",
    "ManagementPlanningError",
    "ManagementRun",
    "ModelManagementPlanner",
    "groq_management_call",
]
