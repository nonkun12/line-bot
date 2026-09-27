"""Exact identity gate for distributed-agent execution.

This module is deliberately separate from capability approval. A lifecycle state
or catalog entry never grants execution permission. Callers must present the
exact approved version, source SHA, and catalog digest they intend to execute,
and the gate rejects every mismatch before dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agent_specs import AgentLifecycle
from .distributed_agent_versions import (
    DistributedAgentVersion,
    DistributedAgentVersionRegistry,
)


class DistributedExecutionGateError(PermissionError):
    """Execution was rejected because the approved identity did not match."""


@dataclass(frozen=True)
class ExecutionIdentity:
    agent_key: str
    version: str
    git_sha: str
    catalog_digest: str


def require_exact_execution_identity(
    registry: DistributedAgentVersionRegistry,
    identity: ExecutionIdentity,
) -> DistributedAgentVersion:
    """Return the exact approved record or fail closed.

    This function intentionally accepts the observed execution identity as an
    explicit argument. A caller must obtain that identity from the immutable
    execution artifact/checkout immediately before dispatch; this gate never
    infers it from the requested version or from a mutable "latest" lookup.
    """
    try:
        record = registry.require_exact(
            identity.agent_key,
            version=identity.version,
            git_sha=identity.git_sha,
            catalog_digest_value=identity.catalog_digest,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise DistributedExecutionGateError(
            f"exact distributed execution identity rejected: {identity.agent_key}"
        ) from exc

    if record.lifecycle is not AgentLifecycle.ENABLED:
        raise DistributedExecutionGateError(
            f"distributed agent is not enabled: {identity.agent_key}@{identity.version}"
        )
    if record.git_sha != identity.git_sha:
        raise DistributedExecutionGateError("approved source SHA mismatch")
    if record.catalog_digest != identity.catalog_digest:
        raise DistributedExecutionGateError("approved catalog digest mismatch")
    return record


__all__ = [
    "DistributedExecutionGateError",
    "ExecutionIdentity",
    "require_exact_execution_identity",
]
