"""Governed Agent metadata and lifecycle scaffolding.

This registry complements ``core.agents.AgentRegistry``.  The existing
registry resolves executable agents; this module records what an Agent is
allowed to do and whether it has passed the lifecycle gates required before
activation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class AgentLifecycle(str, Enum):
    GENERATED = "generated"
    VALIDATED = "validated"
    TESTED = "tested"
    REVIEWED = "reviewed"
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    purpose: str
    input_contract: str
    output_contract: str
    allowed_tools: tuple[str, ...] = ()
    resource_scope: tuple[str, ...] = ()
    safety_constraints: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    lifecycle: AgentLifecycle = AgentLifecycle.GENERATED
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        name: str,
        purpose: str,
        input_contract: str,
        output_contract: str,
        allowed_tools: Iterable[str] = (),
        resource_scope: Iterable[str] = (),
        safety_constraints: Iterable[str] = (),
        tests: Iterable[str] = (),
        lifecycle: AgentLifecycle = AgentLifecycle.GENERATED,
        metadata: dict[str, str] | None = None,
    ) -> "AgentSpec":
        return cls(
            name=name.strip(),
            purpose=purpose.strip(),
            input_contract=input_contract.strip(),
            output_contract=output_contract.strip(),
            allowed_tools=tuple(str(value).strip() for value in allowed_tools if str(value).strip()),
            resource_scope=tuple(str(value).strip() for value in resource_scope if str(value).strip()),
            safety_constraints=tuple(str(value).strip() for value in safety_constraints if str(value).strip()),
            tests=tuple(str(value).strip() for value in tests if str(value).strip()),
            lifecycle=lifecycle,
            metadata=dict(metadata or {}),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.name:
            errors.append("name is required")
        if not self.purpose:
            errors.append("purpose is required")
        if not self.input_contract:
            errors.append("input_contract is required")
        if not self.output_contract:
            errors.append("output_contract is required")
        if not self.safety_constraints:
            errors.append("at least one safety constraint is required")
        if not self.tests:
            errors.append("at least one validation test is required")
        return tuple(errors)

    def transition(self, target: AgentLifecycle) -> "AgentSpec":
        allowed = {
            AgentLifecycle.GENERATED: {AgentLifecycle.VALIDATED},
            AgentLifecycle.VALIDATED: {AgentLifecycle.TESTED},
            AgentLifecycle.TESTED: {AgentLifecycle.REVIEWED},
            AgentLifecycle.REVIEWED: {AgentLifecycle.ENABLED},
            AgentLifecycle.ENABLED: {AgentLifecycle.DISABLED},
            AgentLifecycle.DISABLED: {AgentLifecycle.VALIDATED},
        }
        if target not in allowed[self.lifecycle]:
            raise ValueError(f"invalid agent lifecycle transition: {self.lifecycle} -> {target}")
        if target == AgentLifecycle.VALIDATED:
            errors = self.validate()
            if errors:
                raise ValueError("agent validation failed: " + "; ".join(errors))
        return AgentSpec(
            name=self.name,
            purpose=self.purpose,
            input_contract=self.input_contract,
            output_contract=self.output_contract,
            allowed_tools=self.allowed_tools,
            resource_scope=self.resource_scope,
            safety_constraints=self.safety_constraints,
            tests=self.tests,
            lifecycle=target,
            metadata=dict(self.metadata),
        )


class AgentSpecRegistry:
    """In-memory governed registry; persistence is deliberately provider-neutral."""

    def __init__(self, specs: Iterable[AgentSpec] = ()) -> None:
        self._specs: dict[str, AgentSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: AgentSpec) -> None:
        if not isinstance(spec, AgentSpec):
            raise TypeError("spec must be an AgentSpec")
        if not spec.name:
            raise ValueError("agent name is required")
        if spec.name in self._specs:
            raise ValueError(f"agent already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> AgentSpec | None:
        return self._specs.get(str(name).strip())

    def require(self, name: str) -> AgentSpec:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"unknown agent: {name}")
        return spec

    def update(self, spec: AgentSpec) -> None:
        if spec.name not in self._specs:
            raise KeyError(f"unknown agent: {spec.name}")
        self._specs[spec.name] = spec

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def enabled(self) -> tuple[AgentSpec, ...]:
        return tuple(spec for spec in self._specs.values() if spec.lifecycle == AgentLifecycle.ENABLED)


__all__ = ["AgentLifecycle", "AgentSpec", "AgentSpecRegistry"]
