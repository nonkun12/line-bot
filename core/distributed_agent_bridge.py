"""Bridge existing channel agents into the provider-neutral distributed runtime."""
from __future__ import annotations

from collections.abc import Mapping

from .agents import Agent, AgentRequest
from .distributed_domain_executor import HandlerExecutor
from .distributed_executor_registry import DistributedExecutorRegistry
from .multi_agent import AgentRole, AgentTask


_AGENT_NAMES: Mapping[AgentRole, str] = {
    AgentRole.VOICE: "voice",
    AgentRole.ENGLISH: "english_learning",
    AgentRole.NEWS: "ai_news",
    AgentRole.STOCKS: "stocks",
    AgentRole.MARKET: "global_market",
    AgentRole.JOBS: "job_seeking",
    AgentRole.MUSIC: "music",
    AgentRole.VIDEO: "video",
}


def build_agent_registry(agent_registry) -> DistributedExecutorRegistry:
    """Adapt explicitly registered Core agents without creating providers."""
    registry = DistributedExecutorRegistry()
    for role, agent_name in _AGENT_NAMES.items():
        agent = agent_registry.get(agent_name)
        registry.register(role, HandlerExecutor(_build_handler(agent)))
    return registry


def _build_handler(agent: Agent):
    def handle(task: AgentTask) -> str:
        request = AgentRequest(
            user_id=task.task_id,
            message=task.instruction,
            channel="distributed",
            metadata={"distributed_role": task.role.value},
        )
        if not agent.can_handle(request):
            raise RuntimeError(f"agent rejected distributed request: {agent.name}")
        response = agent.handle(request)
        if not isinstance(response.text, str):
            raise TypeError("core agent response text must be str")
        return response.text

    return handle
