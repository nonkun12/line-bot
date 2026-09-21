"""Safety-bounded version registry for the canonical distributed AI catalog.

This registry records identity only. It never grants tools, permissions, or
execution capability. Runtime execution must use an exact version/SHA/digest
match and a separately approved safety gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable

from .agent_specs import AgentLifecycle
from .distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG, DistributedAgentDescriptor

_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$",
    re.ASCII,
)
_SHA_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)


def catalog_digest(descriptor: DistributedAgentDescriptor) -> str:
    """Return a deterministic digest of the catalog identity/capability metadata."""
    payload = {
        "role": descriptor.role.value,
        "key": descriptor.key,
        "agent_name": descriptor.agent_name,
        "label": descriptor.label,
        "icon": descriptor.icon,
        "detail": descriptor.detail,
        "capability": descriptor.capability,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class DistributedAgentVersion:
    """Immutable logical version bound to exact source and catalog identity."""

    agent_key: str
    version: str = "0.1.0"
    lifecycle: AgentLifecycle = AgentLifecycle.GENERATED
    git_sha: str | None = None
    catalog_digest: str | None = None

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not isinstance(self.agent_key, str) or not self.agent_key:
            errors.append("agent_key is required and must be an exact string")
        elif self.agent_key != self.agent_key.strip() or self.agent_key.casefold() != self.agent_key:
            errors.append("agent_key must be canonical (no surrounding whitespace or case changes)")
        if not isinstance(self.version, str) or not _VERSION_RE.fullmatch(self.version):
            errors.append("version must be SemVer, optionally with a prerelease")
        if self.git_sha is not None and (
            not isinstance(self.git_sha, str) or not _SHA_RE.fullmatch(self.git_sha)
        ):
            errors.append("git_sha must be a full 40-character hexadecimal commit SHA")
        if not isinstance(self.lifecycle, AgentLifecycle):
            errors.append("lifecycle must be an AgentLifecycle")
        if self.catalog_digest is not None and (
            not isinstance(self.catalog_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.catalog_digest, re.ASCII)
        ):
            errors.append("catalog_digest must be a 64-character hexadecimal SHA-256 digest")
        if self.lifecycle == AgentLifecycle.ENABLED and (self.git_sha is None or self.catalog_digest is None):
            errors.append("ENABLED versions require git_sha and catalog_digest")
        return tuple(errors)


class DistributedAgentVersionRegistry:
    """Fail-closed, append-only registry with an explicit freeze boundary."""

    def __init__(self, versions: Iterable[DistributedAgentVersion] = ()) -> None:
        self._versions: dict[str, tuple[DistributedAgentVersion, ...]] = {}
        self._catalog = {item.key: item for item in DISTRIBUTED_AGENT_CATALOG}
        self._frozen = False
        for version in versions:
            self.register(version)

    def register(self, version: DistributedAgentVersion) -> None:
        if self._frozen:
            raise RuntimeError("distributed agent version registry is frozen")
        if not isinstance(version, DistributedAgentVersion):
            raise TypeError("version must be a DistributedAgentVersion")
        errors = version.validate()
        if errors:
            raise ValueError("invalid distributed agent version: " + "; ".join(errors))
        if version.agent_key not in self._catalog:
            raise KeyError(f"agent is not in canonical catalog: {version.agent_key}")
        if version.catalog_digest is not None and version.catalog_digest != catalog_digest(self._catalog[version.agent_key]):
            raise ValueError("catalog_digest does not match canonical catalog")
        history = self._versions.setdefault(version.agent_key, ())
        if any(item.version == version.version for item in history):
            raise ValueError(f"version already registered: {version.agent_key}@{version.version}")
        self._versions[version.agent_key] = (*history, version)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def get(self, agent_key: str) -> DistributedAgentVersion | None:
        if not isinstance(agent_key, str):
            return None
        return self._versions.get(agent_key, ())[-1] if self._versions.get(agent_key) else None

    def require(self, agent_key: str) -> DistributedAgentVersion:
        version = self.get(agent_key)
        if version is None:
            raise KeyError(f"no version registered for distributed agent: {agent_key}")
        return version

    def require_exact(
        self,
        agent_key: str,
        *,
        version: str,
        git_sha: str,
        catalog_digest_value: str,
    ) -> DistributedAgentVersion:
        """Require exact identity; never resolve a moving 'latest' reference."""
        record = self.require(agent_key)
        if (record.version, record.git_sha, record.catalog_digest) != (
            version,
            git_sha,
            catalog_digest_value,
        ):
            raise PermissionError("distributed agent registry/actual identity mismatch")
        return record

    def keys(self) -> tuple[str, ...]:
        return tuple(self._versions)

    def history(self, agent_key: str) -> tuple[DistributedAgentVersion, ...]:
        return self._versions.get(agent_key, ())

    def rollback_target(self, agent_key: str) -> DistributedAgentVersion:
        candidates = [
            item for item in self.history(agent_key)
            if item.lifecycle in {
                AgentLifecycle.TESTED,
                AgentLifecycle.REVIEWED,
                AgentLifecycle.ENABLED,
            }
        ]
        if len(candidates) < 2:
            raise KeyError(f"no prior known-good version for distributed agent: {agent_key}")
        return candidates[-2]

    def all_registered(self) -> bool:
        return frozenset(self._versions) == frozenset(self._catalog)


def build_default_distributed_agent_version_registry(
    *,
    git_sha: str | None = None,
    version: str = "0.1.0",
) -> DistributedAgentVersionRegistry:
    """Build non-executable catalog records for bootstrap/tests.

    Records intentionally start at GENERATED. Production activation must supply
    an exact SHA and catalog digest and pass an independent safety gate.
    """
    registry = DistributedAgentVersionRegistry(
        DistributedAgentVersion(
            agent_key=item.key,
            version=version,
            lifecycle=AgentLifecycle.GENERATED,
            git_sha=git_sha,
            catalog_digest=catalog_digest(item) if git_sha else None,
        )
        for item in DISTRIBUTED_AGENT_CATALOG
    )
    registry.freeze()
    return registry


__all__ = [
    "DistributedAgentVersion",
    "DistributedAgentVersionRegistry",
    "build_default_distributed_agent_version_registry",
    "catalog_digest",
]
