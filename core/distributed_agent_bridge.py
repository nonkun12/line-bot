"""Bridge existing channel agents into the provider-neutral distributed runtime."""

from __future__ import annotations

from collections.abc import Mapping

from .agents import Agent, AgentRequest
from .distributed_execution_artifact import ExecutionArtifactProvider
from .distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from .distributed_agent_versions import DistributedAgentVersionRegistry
from .distributed_domain_executor import HandlerExecutor
from .distributed_execution_gate import require_exact_execution_identity
from .distributed_executor_registry import DistributedExecutorRegistry
from .multi_agent import AgentRole, AgentTask
from .specialist_gate import assert_specialist_approved


_AGENT_NAMES: Mapping[AgentRole, str] = {
    descriptor.role: descriptor.agent_name
    for descriptor in DISTRIBUTED_AGENT_CATALOG
    if descriptor.role is not AgentRole.GENERAL
}


def build_agent_registry(
    agent_registry,
    *,
    version_registry: DistributedAgentVersionRegistry,
    artifact_provider: ExecutionArtifactProvider,
) -> DistributedExecutorRegistry:
    """Adapt explicitly registered agents behind an exact identity gate.

    Both the immutable execution artifact and version registry are mandatory.
    There is deliberately no legacy bypass: execution must prove the exact
    version/SHA/catalog identity immediately before the agent handler runs.
    """
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
            HandlerExecutor(
                _build_handler(
                    role,
                    agent,
                    version_registry=version_registry,
                    artifact_provider=artifact_provider,
                )
            ),
        )
    return registry


def _build_handler(
    role: AgentRole,
    agent: Agent,
    *,
    version_registry: DistributedAgentVersionRegistry,
    artifact_provider: ExecutionArtifactProvider,
):
    def handle(task: AgentTask) -> str:
        # Last-mile choke point: role + exact immutable execution identity
        # must pass before any specialist agent code is invoked.
        if task.role is not role:
            raise RuntimeError(
                f"task role {task.role.value} does not match executor role {role.value}"
            )

        artifact = artifact_provider.get(agent.name)
        require_exact_execution_identity(version_registry, artifact.identity)
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
