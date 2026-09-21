"""Bridge existing channel agents into the provider-neutral distributed runtime."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from .agents import Agent, AgentRequest
from .distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from .distributed_domain_executor import HandlerExecutor
from .distributed_agent_versions import DistributedAgentVersionRegistry
from .distributed_execution_gate import ExecutionIdentity, require_exact_execution_identity
from .distributed_executor_registry import DistributedExecutorRegistry
from .multi_agent import AgentRole, AgentTask
from .specialist_gate import assert_specialist_approved

_AGENT_NAMES: Mapping[AgentRole, str] = {
    descriptor.role: descriptor.agent_name
    for descriptor in DISTRIBUTED_AGENT_CATALOG
    if descriptor.role is not AgentRole.GENERAL
}
IdentityProvider = Callable[[str], ExecutionIdentity]

def build_agent_registry(agent_registry, *, version_registry: DistributedAgentVersionRegistry, identity_provider: IdentityProvider) -> DistributedExecutorRegistry:
    """Adapt Core agents with capability and exact-identity gates."""
    if version_registry is None:
        raise ValueError("version_registry is required")
    if not callable(identity_provider):
        raise TypeError("identity_provider must be callable")
    registry = DistributedExecutorRegistry()
    for role, agent_name in _AGENT_NAMES.items():
        try:
            agent = agent_registry.get(agent_name)
        except KeyError:
            continue
        if agent is None:
            continue
        registry.register(
            role,
            HandlerExecutor(_build_handler(
                role, agent,
                version_registry=version_registry,
                identity_provider=identity_provider,
            )),
        )
    return registry

def _build_handler(role: AgentRole, agent: Agent, *, version_registry: DistributedAgentVersionRegistry, identity_provider: IdentityProvider):
    def handle(task: AgentTask) -> str:
        if task.role is not role:
            raise RuntimeError(f"task role {task.role.value} does not match executor role {role.value}")
        assert_specialist_approved(task.role)
        agent_key = _AGENT_NAMES[role]
        identity = identity_provider(agent_key)
        if identity.agent_key != agent_key:
            raise PermissionError("execution identity agent key mismatch")
        require_exact_execution_identity(version_registry, identity)
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
