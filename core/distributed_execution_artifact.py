"""Trusted execution-artifact identity boundary for distributed AI dispatch.

The provider does not resolve a moving registry entry and does not grant
capabilities. Callers must supply an immutable execution artifact identity
obtained from the artifact/checkout they are about to execute. The identity is
then checked by distributed_execution_gate immediately before dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .distributed_execution_gate import ExecutionIdentity


@dataclass(frozen=True)
class ExecutionArtifact:
    """Immutable identity recorded for one concrete execution artifact."""

    identity: ExecutionIdentity
    artifact_id: str

    def validate(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id:
            raise ValueError("artifact_id is required")
        if self.identity.git_sha != self.identity.git_sha.lower():
            raise ValueError("execution artifact git_sha must be lowercase")
        if len(self.identity.git_sha) != 40:
            raise ValueError("execution artifact git_sha must be a full commit SHA")
        if len(self.identity.catalog_digest) != 64:
            raise ValueError("execution artifact catalog_digest must be SHA-256")


class ExecutionArtifactProvider(Protocol):
    """Provider for an already-created, immutable execution artifact."""

    def get(self, agent_key: str) -> ExecutionArtifact:
        """Return the exact artifact selected for this agent or fail closed."""


class StaticExecutionArtifactProvider:
    """Test/bootstrap provider; production callers must use a trusted artifact source."""

    def __init__(self, artifacts: tuple[ExecutionArtifact, ...]) -> None:
        self._artifacts = {item.identity.agent_key: item for item in artifacts}

    def get(self, agent_key: str) -> ExecutionArtifact:
        artifact = self._artifacts.get(agent_key)
        if artifact is None:
            raise PermissionError(f"no execution artifact for distributed agent: {agent_key}")
        artifact.validate()
        return artifact


__all__ = [
    "ExecutionArtifact",
    "ExecutionArtifactProvider",
    "StaticExecutionArtifactProvider",
]
