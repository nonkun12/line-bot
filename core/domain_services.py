"""Explicit provider-neutral domain service contracts.

These adapters keep external I/O outside the distributed runtime. Each domain
must be bound explicitly by the caller; no API keys, network calls, or fallback
providers are created here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .multi_agent import AgentRole, AgentTask
from .distributed_domain_executor import HandlerExecutor
from .distributed_executor_registry import DistributedExecutorRegistry

DomainHandler = Callable[[AgentTask], str]


@dataclass(frozen=True)
class DomainService:
    role: AgentRole
    handler: DomainHandler

    def execute(self, task: AgentTask) -> str:
        result = self.handler(task)
        if not isinstance(result, str):
            raise TypeError("domain service handler must return str")
        return result


def build_domain_services(
    bindings: Mapping[AgentRole, DomainHandler],
) -> tuple[DomainService, ...]:
    services = []
    for role, handler in bindings.items():
        if not isinstance(role, AgentRole):
            raise TypeError("domain service role must be an AgentRole")
        if not callable(handler):
            raise TypeError("domain service handler must be callable")
        services.append(DomainService(role, handler))
    return tuple(services)


def build_explicit_domain_registry(
    bindings: Mapping[AgentRole, DomainHandler],
) -> DistributedExecutorRegistry:
    registry = DistributedExecutorRegistry()
    for service in build_domain_services(bindings):
        registry.register(service.role, HandlerExecutor(service.handler))
    return registry
