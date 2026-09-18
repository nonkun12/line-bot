"""Adapter from existing Core agents to the distributed AgentExecutor contract.

The adapter preserves the existing AgentRegistry and channel-neutral AgentRequest
while allowing the new management layer to delegate bounded specialist tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .agents import Agent, AgentRegistry, AgentRequest
from .multi_agent import AgentExecutor, AgentResult, AgentRole, AgentTask


ROLE_TO_AGENT_NAME: Mapping[AgentRole, str] = {
    AgentRole.GENERAL: "normal",
    AgentRole.VOICE: "voice",
    AgentRole.ENGLISH: "english_learning",
    AgentRole.NEWS: "ai_news",
    AgentRole.STOCKS: "stocks",
    AgentRole.JOBS: "job_seeking",
    AgentRole.MUSIC: "music",
    AgentRole.VIDEO: "video",
}


@dataclass(frozen=True)
class SpecialistExecutorFactory:
    """Build request-bound distributed executors from the existing registry."""

    registry: AgentRegistry

    def build(self, request: AgentRequest) -> dict[AgentRole, AgentExecutor]:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        executors: dict[AgentRole, AgentExecutor] = {}
        for role, name in ROLE_TO_AGENT_NAME.items():
            try:
                agent = self.registry.get(name)
            except KeyError:
                continue
            executors[role] = RegistrySpecialistExecutor(agent, request)
        return executors


class RegistrySpecialistExecutor(AgentExecutor):
    """Execute one task through an existing channel-neutral Core Agent."""

    def __init__(self, agent: Agent, request: AgentRequest) -> None:
        self._agent = agent
        self._request = request

    @property
    def agent_name(self) -> str:
        return self._agent.name

    def execute(self, task: AgentTask) -> AgentResult:
        if task.role not in ROLE_TO_AGENT_NAME:
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary=f"role is not a specialist agent: {task.role.value}",
            )
        if ROLE_TO_AGENT_NAME[task.role] != self._agent.name:
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary=f"executor is not assigned to role: {task.role.value}",
            )
        try:
            response = self._agent.handle(
                AgentRequest(
                    user_id=self._request.user_id,
                    message=task.instruction,
                    channel=self._request.channel,
                    metadata={
                        **dict(self._request.metadata),
                        "management_task_id": task.task_id,
                        "management_role": task.role.value,
                        "declared_resources": sorted(task.resources),
                    },
                )
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary=f"specialist execution failed: {type(exc).__name__}: {exc}",
            )
        if not response.text or not response.text.strip():
            return AgentResult(
                task_id=task.task_id,
                success=False,
                summary="specialist returned empty response",
            )
        return AgentResult(
            task_id=task.task_id,
            success=True,
            summary=response.text.strip()[:4000],
        )


def build_registry_executors(
    registry: AgentRegistry,
    request: AgentRequest,
) -> dict[AgentRole, AgentExecutor]:
    return SpecialistExecutorFactory(registry).build(request)


__all__ = [
    "ROLE_TO_AGENT_NAME",
    "RegistrySpecialistExecutor",
    "SpecialistExecutorFactory",
    "build_registry_executors",
]
