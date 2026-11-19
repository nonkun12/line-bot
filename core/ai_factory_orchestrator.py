"""Human-gated orchestration for the AI Factory (Stages 126-130).

This module connects capability-gap discovery, evidence-backed collaboration,
agent candidate generation, catalog governance, and bounded LOOP ticks through
provider-neutral protocols. It does not call models, execute generated code,
write files, schedule workflows, grant permissions, merge, or deploy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Protocol, Sequence

from .agent_collaboration_pipeline import CollaborationPacket, CollaborationStage


class FactoryStage(str, Enum):
    ORCHESTRATE = "126"
    BUILD = "127"
    VERIFY = "128"
    CATALOG = "129"
    LOOP = "130"


class CandidateState(str, Enum):
    PROPOSED = "proposed"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    ENABLED = "enabled"


@dataclass(frozen=True)
class CapabilityGapRequest:
    gap_id: str
    capability: str
    description: str
    evidence: tuple[str, ...]

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.gap_id.strip():
            errors.append("gap_id is required")
        if not self.capability.strip():
            errors.append("capability is required")
        if not self.description.strip():
            errors.append("description is required")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            errors.append("gap evidence is required")
        return tuple(errors)


@dataclass(frozen=True)
class ApprovalReceipt:
    candidate_id: str
    scope: str
    approved_by: str
    approval_id: str


@dataclass(frozen=True)
class AgentCandidate:
    candidate_id: str
    gap_id: str
    capability: str
    agent_name: str
    artifact_sha256: str
    test_evidence: tuple[str, ...]
    review_evidence: tuple[str, ...]
    state: CandidateState = CandidateState.AWAITING_APPROVAL
    approval_id: str | None = None

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for key, value in (
            ("candidate_id", self.candidate_id),
            ("gap_id", self.gap_id),
            ("capability", self.capability),
            ("agent_name", self.agent_name),
            ("artifact_sha256", self.artifact_sha256),
        ):
            if not value.strip():
                errors.append(f"{key} is required")
        if len(self.artifact_sha256) != 64:
            errors.append("artifact_sha256 must be a SHA-256 digest")
        if not self.test_evidence or not self.review_evidence:
            errors.append("test and review evidence are required")
        return tuple(errors)


@dataclass(frozen=True)
class CatalogEntry:
    candidate: AgentCandidate
    state: CandidateState
    approved_by: str | None = None


class CollaborationRunner(Protocol):
    def collaborate(self, gap: CapabilityGapRequest) -> CollaborationPacket:
        """Return a completed Stage 123 packet with independent role evidence."""
        ...


class CandidateFactory(Protocol):
    def create_candidate(self, capability_gap: str) -> object:
        """Return a Stage 121 AgentCreationRecord-like reviewed candidate."""
        ...


class ApprovalVerifier(Protocol):
    def verify(self, candidate: AgentCandidate, receipt: ApprovalReceipt) -> bool:
        """Verify an out-of-band human approval for the exact candidate and scope."""
        ...


class AgentActivator(Protocol):
    def activate(self, candidate: AgentCandidate) -> bool:
        """Perform an explicitly approved activation through a separately gated adapter."""
        ...


class SpecialistAgentCatalog:
    """Metadata-only catalog; entries are never executable by themselves."""

    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}

    def register_approved(
        self,
        candidate: AgentCandidate,
        receipt: ApprovalReceipt,
        verifier: ApprovalVerifier,
    ) -> CatalogEntry:
        errors = candidate.validate()
        if errors:
            raise ValueError("invalid candidate: " + "; ".join(errors))
        if candidate.state is not CandidateState.AWAITING_APPROVAL:
            raise ValueError("only candidates awaiting approval can be registered")
        if receipt.candidate_id != candidate.candidate_id or receipt.scope != "register":
            raise PermissionError("approval receipt does not match candidate registration")
        if not receipt.approved_by.strip() or not receipt.approval_id.strip():
            raise PermissionError("complete human approval receipt is required")
        if verifier.verify(candidate, receipt) is not True:
            raise PermissionError("human approval verification failed")
        if candidate.candidate_id in self._entries:
            raise ValueError("candidate already exists in catalog")
        approved = AgentCandidate(
            **{
                **candidate.__dict__,
                "state": CandidateState.APPROVED,
                "approval_id": receipt.approval_id,
            }
        )
        entry = CatalogEntry(approved, CandidateState.APPROVED, receipt.approved_by)
        self._entries[candidate.candidate_id] = entry
        return entry

    def mark_enabled(
        self,
        candidate_id: str,
        receipt: ApprovalReceipt,
        verifier: ApprovalVerifier,
        activator: AgentActivator,
    ) -> CatalogEntry:
        entry = self._entries.get(candidate_id)
        if entry is None:
            raise KeyError("unknown catalog candidate")
        if entry.state is not CandidateState.APPROVED:
            raise PermissionError("only approved candidates may be enabled")
        if receipt.candidate_id != candidate_id or receipt.scope != "enable":
            raise PermissionError("separate human enable approval is required")
        if verifier.verify(entry.candidate, receipt) is not True:
            raise PermissionError("human enable approval verification failed")
        if activator.activate(entry.candidate) is not True:
            raise RuntimeError("activation adapter did not confirm activation")
        enabled = CatalogEntry(
            AgentCandidate(
                **{
                    **entry.candidate.__dict__,
                    "state": CandidateState.ENABLED,
                }
            ),
            CandidateState.ENABLED,
            receipt.approved_by,
        )
        self._entries[candidate_id] = enabled
        return enabled

    def get(self, candidate_id: str) -> CatalogEntry | None:
        return self._entries.get(candidate_id)

    def find_enabled(self, capability: str) -> tuple[CatalogEntry, ...]:
        key = capability.strip().casefold()
        return tuple(
            entry for entry in self._entries.values()
            if entry.state is CandidateState.ENABLED
            and entry.candidate.capability.strip().casefold() == key
        )

    def entries(self) -> tuple[CatalogEntry, ...]:
        return tuple(self._entries.values())


@dataclass(frozen=True)
class OrchestrationResult:
    gap_id: str
    stage: FactoryStage
    candidate: AgentCandidate | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class LoopTickReport:
    tick_id: str
    processed: tuple[OrchestrationResult, ...]
    stopped_reason: str | None = None

    @property
    def created_candidates(self) -> int:
        return sum(item.candidate is not None for item in self.processed)

    @property
    def blocked(self) -> int:
        return sum(item.blocked_reason is not None for item in self.processed)


@dataclass(frozen=True)
class LoopSafety:
    kill_switch_active: bool = False
    hold_active: bool = False
    evidence_complete: bool = True
    budget_available: bool = True
    max_candidates_per_tick: int = 4


class AIFactoryOrchestrator:
    """Coordinate Stages 126-130; propose candidates but never self-approve."""

    def __init__(
        self,
        collaboration: CollaborationRunner,
        factory: CandidateFactory,
        catalog: SpecialistAgentCatalog | None = None,
    ) -> None:
        self.collaboration = collaboration
        self.factory = factory
        self.catalog = catalog or SpecialistAgentCatalog()

    def process_gap(self, gap: CapabilityGapRequest) -> OrchestrationResult:
        errors = gap.validate()
        if errors:
            return OrchestrationResult(gap.gap_id, FactoryStage.ORCHESTRATE, blocked_reason="; ".join(errors))
        try:
            packet = self.collaboration.collaborate(gap)
            if not isinstance(packet, CollaborationPacket):
                raise TypeError("collaboration adapter must return CollaborationPacket")
            packet_errors = packet.validate()
            if packet_errors:
                raise ValueError("invalid collaboration evidence: " + "; ".join(packet_errors))
            if packet.current_stage is not CollaborationStage.COMPLETE:
                raise PermissionError("Stage 123 collaboration is not complete")
            if len(packet.evidence) != 4 or {item.stage for item in packet.evidence} != {
                CollaborationStage.DESIGN, CollaborationStage.BUILD,
                CollaborationStage.TEST, CollaborationStage.REVIEW,
            }:
                raise PermissionError("all four independent collaboration stages are required")
            record = self.factory.create_candidate(gap.gap_id)
            build = getattr(record, "build", None)
            tests = getattr(record, "tests", None)
            review = getattr(record, "review", None)
            spec = getattr(build, "spec", None)
            files = getattr(build, "files", ())
            if spec is None or tests is None or review is None:
                raise TypeError("factory returned an incomplete candidate record")
            if getattr(tests, "passed", False) is not True or not getattr(tests, "evidence", ()):
                raise PermissionError("sandbox tests did not pass with evidence")
            if getattr(review, "approved", False) is not True or getattr(review, "blockers", ()):
                raise PermissionError("independent review did not approve")
            material = "\n".join(
                f"{getattr(item, 'path', '')}\0{getattr(item, 'content', '')}" for item in files
            )
            if not material.strip():
                raise ValueError("generated artifacts are missing")
            digest = sha256(material.encode("utf-8")).hexdigest()
            name = str(getattr(spec, "name", "")).strip()
            candidate_id = f"{gap.gap_id}:{digest[:12]}"
            candidate = AgentCandidate(
                candidate_id=candidate_id,
                gap_id=gap.gap_id,
                capability=gap.capability,
                agent_name=name,
                artifact_sha256=digest,
                test_evidence=tuple(str(item) for item in tests.evidence),
                review_evidence=tuple(str(item) for item in review.findings) or ("independent review approved",),
            )
            candidate_errors = candidate.validate()
            if candidate_errors:
                raise ValueError("candidate validation failed: " + "; ".join(candidate_errors))
            return OrchestrationResult(gap.gap_id, FactoryStage.CATALOG, candidate=candidate)
        except Exception as exc:
            return OrchestrationResult(
                gap.gap_id,
                FactoryStage.VERIFY,
                blocked_reason=f"{type(exc).__name__}: {exc}",
            )

    def run_tick(
        self,
        tick_id: str,
        gaps: Sequence[CapabilityGapRequest],
        *,
        safety: LoopSafety = LoopSafety(),
    ) -> LoopTickReport:
        """Run one bounded tick; external scheduler owns cadence and persistence."""
        if not tick_id.strip():
            return LoopTickReport("", (), "tick_id is required")
        if safety.max_candidates_per_tick < 1 or safety.max_candidates_per_tick > 4:
            return LoopTickReport(tick_id, (), "max_candidates_per_tick must be between 1 and 4")
        if safety.kill_switch_active:
            return LoopTickReport(tick_id, (), "global kill switch is active")
        if safety.hold_active:
            return LoopTickReport(tick_id, (), "HOLD is active")
        if not safety.evidence_complete:
            return LoopTickReport(tick_id, (), "required evidence is incomplete")
        if not safety.budget_available:
            return LoopTickReport(tick_id, (), "safe execution budget is unavailable")
        seen: set[str] = set()
        results: list[OrchestrationResult] = []
        for gap in gaps:
            if len(results) >= safety.max_candidates_per_tick:
                break
            if gap.gap_id in seen:
                results.append(
                    OrchestrationResult(gap.gap_id, FactoryStage.ORCHESTRATE, blocked_reason="duplicate gap id")
                )
                continue
            seen.add(gap.gap_id)
            results.append(self.process_gap(gap))
        return LoopTickReport(tick_id, tuple(results))


__all__ = [
    "FactoryStage", "CandidateState", "CapabilityGapRequest", "ApprovalReceipt",
    "AgentCandidate", "CatalogEntry", "SpecialistAgentCatalog",
    "CollaborationRunner", "CandidateFactory", "ApprovalVerifier", "AgentActivator",
    "OrchestrationResult", "LoopTickReport", "LoopSafety", "AIFactoryOrchestrator",
]
