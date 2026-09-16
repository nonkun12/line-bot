"""Read-only maintenance findings for agents and the integrated AI.

The maintenance layer is intentionally diagnostic-only. It reports conditions
that may need attention but never mutates production state, dependencies, or
agent activation by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


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

    def inspect_version(self, component: str, version: object | None) -> tuple[MaintenanceFinding, ...]:
        component = component.strip()
        if not component:
            raise ValueError("component is required")
        if version is None:
            return (
                MaintenanceFinding(
                    component=component,
                    code="VERSION_MISSING",
                    severity=MaintenanceSeverity.WARNING,
                    message="No registered version metadata was found.",
                ),
            )
        return ()

    def inspect_findings(
        self, findings: Iterable[MaintenanceFinding]
    ) -> tuple[MaintenanceFinding, ...]:
        return tuple(findings)


__all__ = ["AgentMaintenance", "MaintenanceFinding", "MaintenanceSeverity"]
