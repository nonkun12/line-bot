"""Explicit dependency bundle for distributed-agent execution identity."""

from __future__ import annotations

from dataclasses import dataclass

from .distributed_execution_artifact import ExecutionArtifactProvider
from .distributed_agent_versions import DistributedAgentVersionRegistry


@dataclass(frozen=True)
class DistributedExecutionContext:
    """Immutable references required to cross the distributed execution boundary."""

    version_registry: DistributedAgentVersionRegistry
    artifact_provider: ExecutionArtifactProvider


__all__ = ["DistributedExecutionContext"]
