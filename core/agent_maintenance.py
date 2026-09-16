"""Read-only maintenance findings for agents and the integrated AI."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .agent_versioning import AgentVersion


class MaintenanceSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class MaintenanceFinding:
    component: str
    code: str
    severity: MaintenanceSeverity
    message: str


class AgentMaintenance:
    """Collect deterministic, side-effect-free maintenance findings."""

    def inspect_version(
        self, component: str, version: AgentVersion | None
    ) -> tuple[MaintenanceFinding, ...]:
        component = component.strip()
        if not component:
            raise ValueError("component is required")
        if version is None:
            return (
                MaintenanceFinding(
                    component,
                    "VERSION_MISSING",
                    MaintenanceSeverity.WARNING,
                    "No registered version metadata was found.",
                ),
            )
        if not isinstance(version, AgentVersion):
            raise TypeError("version must be an AgentVersion or None")
        if version.agent_name.strip() != component:
            return (
                MaintenanceFinding(
                    component,
                    "VERSION_COMPONENT_MISMATCH",
                    MaintenanceSeverity.ERROR,
                    "Version metadata belongs to a different component.",
                ),
            )
        return ()

    def inspect_findings(
        self, findings: Iterable[MaintenanceFinding]
    ) -> tuple[MaintenanceFinding, ...]:
        return tuple(findings)


__all__ = ["AgentMaintenance", "MaintenanceFinding", "MaintenanceSeverity"]
