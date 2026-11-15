"""Evidence-based discovery of missing specialist AI capabilities.

Static architecture declarations are kept separate from enabled runtime
registrations. Only enabled registrations satisfy a required capability.
This module proposes AgentSpec designs; it never grants permissions, executes
agents, changes registries, or enables candidates.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Mapping, Protocol, Sequence

from .agent_architecture import PLATFORM_COMPONENTS, SPECIALIST_MODULES
from .agent_specs import AgentLifecycle, AgentSpec, AgentSpecRegistry
from .distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from .specialist_registry import SpecialistRegistry


def _normalize(value: str) -> str:
    return "_".join(str(value).strip().casefold().replace("-", " ").split())


@dataclass(frozen=True)
class CapabilityRequirement:
    key: str
    description: str
    input_contract: str = "Capability request with bounded context"
    output_contract: str = "Evidence-backed result matching the capability contract"
    safety_constraints: tuple[str, ...] = (
        "least privilege",
        "read-only by default",
        "no permission escalation",
        "no automatic merge or deployment",
        "human approval required for activation",
    )
    validation_tests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _normalize(self.key):
            raise ValueError("capability key is required")
        if not self.description.strip():
            raise ValueError("capability description is required")
        if not self.input_contract.strip() or not self.output_contract.strip():
            raise ValueError("input and output contracts are required")
        if not self.safety_constraints:
            raise ValueError("safety constraints are required")


@dataclass(frozen=True)
class CapabilityRecord:
    key: str
    source: str
    state: str
    detail: str = ""


@dataclass(frozen=True)
class AgentCapabilityInventory:
    records: tuple[CapabilityRecord, ...] = ()

    @classmethod
    def from_platform(
        cls,
        *,
        specialist_registry: SpecialistRegistry | None = None,
        spec_registry: AgentSpecRegistry | None = None,
    ) -> "AgentCapabilityInventory":
        records: list[CapabilityRecord] = []
        for item in SPECIALIST_MODULES:
            records.append(CapabilityRecord(item.key, "agent_architecture", "declared", item.domain))
        for item in PLATFORM_COMPONENTS:
            records.append(
                CapabilityRecord(item.key, "agent_architecture", "declared", item.responsibility)
            )
        for item in DISTRIBUTED_AGENT_CATALOG:
            records.append(
                CapabilityRecord(item.capability, "distributed_agent_catalog", "declared", item.detail)
            )
        if specialist_registry is not None:
            for specialist in specialist_registry.specialists():
                registration = specialist_registry.get(specialist)
                if registration is not None:
                    records.append(
                        CapabilityRecord(
                            specialist.value,
                            "specialist_registry",
                            "enabled",
                            "registered handler",
                        )
                    )
                    records.extend(
                        CapabilityRecord(value, "specialist_registry", "enabled", specialist.value)
                        for value in registration.capabilities
                    )
        if spec_registry is not None:
            for name in spec_registry.names():
                spec = spec_registry.get(name)
                if spec is not None and spec.lifecycle == AgentLifecycle.ENABLED:
                    records.extend(
                        CapabilityRecord(value, "agent_spec_registry", "enabled", name)
                        for value in spec.metadata.get("capabilities", "").split(",")
                        if value.strip()
                    )
        return cls(tuple(records))

    def providers(self, capability: str, *, enabled_only: bool = True) -> tuple[CapabilityRecord, ...]:
        key = _normalize(capability)
        return tuple(
            item for item in self.records
            if _normalize(item.key) == key and (not enabled_only or item.state == "enabled")
        )

    def declared_only(self, capability: str) -> tuple[CapabilityRecord, ...]:
        key = _normalize(capability)
        return tuple(
            item for item in self.records
            if _normalize(item.key) == key and item.state == "declared"
        )

    def enabled_capabilities(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            item.key for item in self.records if item.state == "enabled"
        ))


@dataclass(frozen=True)
class CapabilityGap:
    gap_id: str
    requirement: CapabilityRequirement
    declared_matches: tuple[CapabilityRecord, ...] = ()
    evidence: tuple[str, ...] = ()

    @property
    def capability(self) -> str:
        return self.requirement.key


@dataclass(frozen=True)
class CapabilityGapReport:
    gaps: tuple[CapabilityGap, ...]
    covered: tuple[str, ...]
    inventory: AgentCapabilityInventory

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)


class CapabilityGapPlanner:
    """Compare explicit capability requirements against enabled registrations."""

    def analyze(
        self,
        requirements: Sequence[CapabilityRequirement],
        inventory: AgentCapabilityInventory,
    ) -> CapabilityGapReport:
        seen: set[str] = set()
        gaps: list[CapabilityGap] = []
        covered: list[str] = []
        for requirement in requirements:
            key = _normalize(requirement.key)
            if key in seen:
                raise ValueError(f"duplicate capability requirement: {requirement.key}")
            seen.add(key)
            providers = inventory.providers(requirement.key, enabled_only=True)
            if providers:
                covered.append(requirement.key)
                continue
            declared = inventory.declared_only(requirement.key)
            evidence = (
                ("architecture/catalog declaration exists but no enabled handler is registered",)
                if declared else
                ("no matching enabled capability or architecture declaration was found",)
            )
            digest = sha256(key.encode("utf-8")).hexdigest()[:12]
            gaps.append(
                CapabilityGap(
                    gap_id=f"capability-gap-{digest}",
                    requirement=requirement,
                    declared_matches=declared,
                    evidence=evidence,
                )
            )
        return CapabilityGapReport(tuple(gaps), tuple(covered), inventory)


class CapabilityGapDesigner(Protocol):
    def design(self, gap: CapabilityGap) -> AgentSpec:
        """Return a GENERATED spec; the downstream AgentFactory validates it."""
        ...


class CapabilityGapArchitect:
    """Adapter allowing Stage 121 AgentFactory to consume a discovered gap."""

    def __init__(self, designer: CapabilityGapDesigner) -> None:
        self.designer = designer
        self._gaps: dict[str, CapabilityGap] = {}

    def bind(self, gap: CapabilityGap) -> str:
        if gap.gap_id in self._gaps and self._gaps[gap.gap_id] != gap:
            raise ValueError("capability gap id collision")
        self._gaps[gap.gap_id] = gap
        return gap.gap_id

    def design(self, capability_gap: str) -> AgentSpec:
        gap = self._gaps.get(str(capability_gap).strip())
        if gap is None:
            raise KeyError(f"unknown capability gap: {capability_gap}")
        spec = self.designer.design(gap)
        if not isinstance(spec, AgentSpec):
            raise TypeError("capability gap designer must return AgentSpec")
        if spec.lifecycle != AgentLifecycle.GENERATED:
            raise ValueError("capability gap designer must return GENERATED spec")
        metadata = dict(spec.metadata)
        metadata["capability_gap_id"] = gap.gap_id
        metadata["capability"] = gap.capability
        metadata["capability_gap_evidence"] = " | ".join(gap.evidence)
        return replace(spec, metadata=metadata)


__all__ = [
    "CapabilityRequirement",
    "CapabilityRecord",
    "AgentCapabilityInventory",
    "CapabilityGap",
    "CapabilityGapReport",
    "CapabilityGapPlanner",
    "CapabilityGapDesigner",
    "CapabilityGapArchitect",
]
