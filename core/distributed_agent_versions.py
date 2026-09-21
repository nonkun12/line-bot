"""Version registry for the distributed AI catalog.

Versions are logical agent versions, separate from Git history. A release
record can bind a version to an exact commit SHA; this module deliberately
does not infer or mutate that binding automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .agent_specs import AgentLifecycle
from .distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG

_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


@dataclass(frozen=True)
class DistributedAgentVersion:
    """Immutable logical version plus optional exact source binding."""

    agent_key: str
    version: str = "0.1.0"
    lifecycle: AgentLifecycle = AgentLifecycle.ENABLED
    git_sha: str | None = None

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.agent_key.strip():
            errors.append("agent_key is required")
        if not _VERSION_RE.fullmatch(self.version.strip()):
            errors.append("version must be SemVer, optionally with a prerelease")
        if self.git_sha is not None and not re.fullmatch(r"[0-9a-f]{7,64}", self.git_sha):
            errors.append("git_sha must be a hexadecimal commit SHA")
        if not isinstance(self.lifecycle, AgentLifecycle):
            errors.append("lifecycle must be an AgentLifecycle")
        return tuple(errors)


class DistributedAgentVersionRegistry:
    """Fail-closed registry keyed only by agents in the canonical catalog."""

    def __init__(self, versions: Iterable[DistributedAgentVersion] = ()) -> None:
        self._versions: dict[str, DistributedAgentVersion] = {}
        self._catalog_keys = frozenset(item.key for item in DISTRIBUTED_AGENT_CATALOG)
        for version in versions:
            self.register(version)

    def register(self, version: DistributedAgentVersion) -> None:
        errors = version.validate()
        if errors:
            raise ValueError("invalid distributed agent version: " + "; ".join(errors))
        key = version.agent_key.strip()
        if key not in self._catalog_keys:
            raise KeyError(f"agent is not in canonical catalog: {key}")
        if key in self._versions:
            raise ValueError(f"version already registered: {key}")
        self._versions[key] = version

    def get(self, agent_key: str) -> DistributedAgentVersion | None:
        return self._versions.get(str(agent_key).strip().casefold())

    def require(self, agent_key: str) -> DistributedAgentVersion:
        version = self.get(agent_key)
        if version is None:
            raise KeyError(f"no version registered for distributed agent: {agent_key}")
        return version

    def keys(self) -> tuple[str, ...]:
        return tuple(self._versions)

    def all_registered(self) -> bool:
        return frozenset(self._versions) == self._catalog_keys


def build_default_distributed_agent_version_registry(
    *,
    git_sha: str | None = None,
    version: str = "0.1.0",
) -> DistributedAgentVersionRegistry:
    """Build a complete catalog registry without granting execution rights."""
    return DistributedAgentVersionRegistry(
        DistributedAgentVersion(
            agent_key=item.key,
            version=version,
            lifecycle=AgentLifecycle.ENABLED,
            git_sha=git_sha,
        )
        for item in DISTRIBUTED_AGENT_CATALOG
    )


__all__ = [
    "DistributedAgentVersion",
    "DistributedAgentVersionRegistry",
    "build_default_distributed_agent_version_registry",
]
