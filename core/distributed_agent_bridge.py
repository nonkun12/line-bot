"""Bridge existing channel agents into the provider-neutral distributed runtime."""
from __future__ import annotations

from collections.abc import Mapping

from .agents import Agent, AgentRequest
from .distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from .distributed_domain_executor import HandlerExecutor
from .distributed_executor_registry import DistributedExecutorRegistry
from .multi_agent import AgentRole, AgentTask
from .specialist_gate import assert_specialist_approved


_AGENT_NAMES: Mapping[AgentRole, str] = {
    descriptor.role: descriptor.agent_name
    for descriptor in DISTRIBUTED_AGENT_CATALOG
    if descriptor.role is not AgentRole.GENERAL
}


def build_agent_registry(agent_registry) -> DistributedExecutorRegistry:
    """Adapt explicitly registered Core agents without creating providers."""
    registry = DistributedExecutorRegistry()
    for role, agent_name in _AGENT_NAMES.items():
        try:
            agent = agent_registry.get(agent_name)
        except KeyError:
            continue
        if agent is None:
            continue
        registry.register(role, HandlerExecutor(_build_handler(role, agent)))
    return registry


def _build_handler(role: AgentRole, agent: Agent):
    def handle(task: AgentTask) -> str:
        # Last-mile choke point: the role that is about to execute must be the
        # role this executor was registered for, and it must be approved.
        if task.role is not role:
            raise RuntimeError(
                f"task role {task.role.value} does not match executor role {role.value}"
            )
        assert_specialist_approved(task.role)
        request = AgentRequest(
            user_id=task.task_id,
            message=task.instruction,
            channel="distributed",
            metadata={"distributed_role": task.role.value, "next_agent": agent.name},
        )
        if not agent.can_handle(request):
            raise RuntimeError(f"agent rejected distributed request: {agent.name}")
        response = agent.handle(request)
        if not isinstance(response.text, str):
            raise TypeError("core agent response text must be str")
        return response.text

    return handle
