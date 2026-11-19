"""Human-gated factory for generating and validating specialist AI agents.

The factory coordinates pluggable Architect, Builder, Sandbox, and Reviewer
adapters. Generated files remain inert artifacts: this module never writes
files, executes generated code, grants tools, or activates an agent implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from .agent_governance import AgentGovernance, AgentGovernanceRecord
from .agent_specs import AgentLifecycle, AgentSpec
from .agent_versioning import AgentVersion


@dataclass(frozen=True)
class GeneratedFile:
    """A proposed file, not a filesystem write."""

    path: str
    content: str


@dataclass(frozen=True)
class AgentBuild:
    spec: AgentSpec
    files: tuple[GeneratedFile, ...]


@dataclass(frozen=True)
class AgentTestReport:
    passed: bool
    evidence: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentReviewReport:
    approved: bool
    findings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


class AgentArchitect(Protocol):
    def design(self, capability_gap: str) -> AgentSpec:
        ...


class AgentBuilder(Protocol):
    def build(self, spec: AgentSpec) -> AgentBuild:
        ...


class AgentSandbox(Protocol):
    def test(self, build: AgentBuild) -> AgentTestReport:
        ...


class AgentReviewer(Protocol):
    def review(self, build: AgentBuild, tests: AgentTestReport) -> AgentReviewReport:
        ...


class HumanApprovalGate(Protocol):
    def approve(self, candidate: "AgentCreationRecord", approved_by: str) -> bool:
        ...


@dataclass(frozen=True)
class AgentCreationRecord:
    build: AgentBuild
    tests: AgentTestReport
    review: AgentReviewReport
    lifecycle: AgentLifecycle = AgentLifecycle.REVIEWED
    approved_by: str | None = None


class AgentFactory:
    """Prepare agent candidates; runtime registration requires explicit approval."""

    ALLOWED_OUTPUT_ROOTS = ("agents/generated/", "tests/agents/generated/")

    def __init__(
        self,
        *,
        architect: AgentArchitect,
        builder: AgentBuilder,
        sandbox: AgentSandbox,
        reviewer: AgentReviewer,
        governance: AgentGovernance | None = None,
        permitted_tools: tuple[str, ...] = (),
        permitted_resource_scopes: tuple[str, ...] = (),
        approval_gate: HumanApprovalGate | None = None,
    ) -> None:
        self.architect = architect
        self.builder = builder
        self.sandbox = sandbox
        self.reviewer = reviewer
        self.governance = governance or AgentGovernance()
        self.permitted_tools = frozenset(permitted_tools)
        self.permitted_resource_scopes = frozenset(permitted_resource_scopes)
        self.approval_gate = approval_gate
        self._records: dict[str, AgentCreationRecord] = {}

    def create_candidate(self, capability_gap: str) -> AgentCreationRecord:
        """Generate and review an inert candidate; never enable or register it."""
        gap = str(capability_gap).strip()
        if not gap:
            raise ValueError("capability_gap is required")

        spec = self.architect.design(gap)
        if not isinstance(spec, AgentSpec):
            raise TypeError("architect must return an AgentSpec")
        if spec.lifecycle != AgentLifecycle.GENERATED:
            raise ValueError("architect must return a GENERATED AgentSpec")
        errors = spec.validate()
        if errors:
            raise ValueError("agent specification invalid: " + "; ".join(errors))
        self._validate_capabilities(spec)
        spec = spec.transition(AgentLifecycle.VALIDATED)

        build = self.builder.build(spec)
        if not isinstance(build, AgentBuild):
            raise TypeError("builder must return an AgentBuild")
        if build.spec != spec:
            raise ValueError("builder must preserve the approved AgentSpec")
        self._validate_files(build.files)
        if spec.name in self._records or self.governance.get(spec.name) is not None:
            raise ValueError(f"agent candidate already exists: {spec.name}")

        tests = self.sandbox.test(build)
        if not isinstance(tests, AgentTestReport):
            raise TypeError("sandbox must return an AgentTestReport")
        if not tests.passed or not tests.evidence or tests.failures:
            raise ValueError("agent sandbox tests did not pass with evidence")
        tested_spec = spec.transition(AgentLifecycle.TESTED)
        build = replace(build, spec=tested_spec)

        review = self.reviewer.review(build, tests)
        if not isinstance(review, AgentReviewReport):
            raise TypeError("reviewer must return an AgentReviewReport")
        if not review.approved or review.blockers:
            raise ValueError("agent review did not approve the candidate")
        reviewed_spec = tested_spec.transition(AgentLifecycle.REVIEWED)
        build = replace(build, spec=reviewed_spec)

        record = AgentCreationRecord(
            build=build,
            tests=tests,
            review=review,
            lifecycle=AgentLifecycle.REVIEWED,
        )
        self._records[spec.name] = record
        return record

    def approve_and_register(
        self,
        name: str,
        *,
        agent: object,
        version: AgentVersion,
        approved_by: str,
    ) -> AgentGovernanceRecord:
        """Register only after the configured human approval gate accepts."""
        approver = str(approved_by).strip()
        if not approver:
            raise ValueError("approved_by is required")

        record = self._records.get(str(name).strip())
        if record is None:
            raise KeyError(f"unknown reviewed candidate: {name}")
        if record.lifecycle != AgentLifecycle.REVIEWED:
            raise ValueError("candidate is not in REVIEWED lifecycle")
        if self.approval_gate is None:
            raise PermissionError("human approval gate is not configured")
        if self.approval_gate.approve(record, approver) is not True:
            raise PermissionError("human approval gate rejected the candidate")

        enabled_spec = record.build.spec.transition(AgentLifecycle.ENABLED)
        if version.agent_name != enabled_spec.name:
            raise ValueError("agent and version names must match")
        enabled_version = replace(version, lifecycle=AgentLifecycle.ENABLED)

        # Governance performs the final consistency checks before activation.
        result = self.governance.register(agent, enabled_spec, enabled_version)
        self._records[enabled_spec.name] = replace(
            record,
            build=replace(record.build, spec=enabled_spec),
            lifecycle=AgentLifecycle.ENABLED,
            approved_by=approver,
        )
        return result

    def get_candidate(self, name: str) -> AgentCreationRecord | None:
        return self._records.get(str(name).strip())

    def candidate_names(self) -> tuple[str, ...]:
        return tuple(self._records)

    def _validate_capabilities(self, spec: AgentSpec) -> None:
        unexpected_tools = set(spec.allowed_tools) - self.permitted_tools
        unexpected_scopes = set(spec.resource_scope) - self.permitted_resource_scopes
        if unexpected_tools:
            raise PermissionError(
                "agent requested tools outside the factory allowlist: "
                + ", ".join(sorted(unexpected_tools))
            )
        if unexpected_scopes:
            raise PermissionError(
                "agent requested resource scopes outside the factory allowlist: "
                + ", ".join(sorted(unexpected_scopes))
            )

    @classmethod
    def _validate_files(cls, files: tuple[GeneratedFile, ...]) -> None:
        if not files:
            raise ValueError("builder returned no generated files")
        seen: set[str] = set()
        has_python = False
        has_test = False
        for item in files:
            if not isinstance(item, GeneratedFile):
                raise TypeError("generated files must be GeneratedFile values")
            path = item.path.strip().replace("\\", "/")
            parts = path.split("/")
            if (
                not path
                or path.startswith("/")
                or any(part in {"", ".", ".."} for part in parts)
                or not path.endswith(".py")
                or not any(path.startswith(root) for root in cls.ALLOWED_OUTPUT_ROOTS)
            ):
                raise ValueError(f"generated file path is outside the factory sandbox: {item.path}")
            if path in seen:
                raise ValueError(f"duplicate generated file path: {path}")
            if not isinstance(item.content, str) or not item.content.strip():
                raise ValueError(f"generated file is empty: {path}")
            seen.add(path)
            has_python = has_python or path.startswith("agents/generated/")
            has_test = has_test or path.startswith("tests/agents/generated/")
        if not has_python or not has_test:
            raise ValueError("builder must provide agent source and isolated test files")


__all__ = [
    "AgentFactory",
    "AgentCreationRecord",
    "AgentBuild",
    "GeneratedFile",
    "AgentTestReport",
    "AgentReviewReport",
    "AgentArchitect",
    "AgentBuilder",
    "AgentSandbox",
    "AgentReviewer",
    "HumanApprovalGate",
]
