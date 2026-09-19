"""Explicit registry for distributed AI domain executors.

The registry is deliberately boring: callers register concrete executors, then
ask it for the mapping consumed by DistributedAgentCoordinator. It never creates
providers, performs I/O, or silently substitutes an implementation.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .agent_runtime import RuntimeExecutor
from .multi_agent import AgentRole


class DistributedExecutorRegistry:
    """Build an explicit, immutable executor mapping for the coordinator."""

    def __init__(self) -> None:
        self._executors: dict[AgentRole, RuntimeExecutor] = {}

    def register(self, role: AgentRole, executor: RuntimeExecutor) -> None:
        if not isinstance(role, AgentRole):
            raise TypeError("role must be an AgentRole")
        if executor is None:
            raise ValueError("executor is required")
        if role in self._executors:
            raise ValueError(f"executor already registered for role: {role.value}")
        self._executors[role] = executor

    def register_many(self, executors: Mapping[AgentRole, RuntimeExecutor]) -> None:
        for role, executor in executors.items():
            self.register(role, executor)

    def has(self, role: AgentRole) -> bool:
        return role in self._executors

    def build(self) -> Mapping[AgentRole, RuntimeExecutor]:
        """Return a read-only snapshot; missing roles remain intentionally absent."""
        return MappingProxyType(dict(self._executors))
