"""Provider-neutral domain service boundary.

Concrete services for voice, English, stocks, news, etc. are injected by the
application. This module only defines a stable callable contract, keeping the
distributed foundation independent from HTTP clients, APIs, and model providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .distributed_domain_executor import HandlerExecutor
from .distributed_executor_registry import DistributedExecutorRegistry
from .multi_agent import AgentRole, AgentTask


@dataclass(frozen=True)
class DomainServiceBinding:
    role: AgentRole
    handler: Callable[[AgentTask], str]


def build_domain_registry(bindings: Mapping[AgentRole, Callable[[AgentTask], str]]) -> DistributedExecutorRegistry:
    """Convert explicitly injected domain handlers into runtime executors."""
    registry = DistributedExecutorRegistry()
    for role, handler in bindings.items():
        _, executor = (role, HandlerExecutor(handler))
        registry.register(role, executor)
    return registry
