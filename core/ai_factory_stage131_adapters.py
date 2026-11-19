"""Concrete, provider-neutral adapters joining AI Factory Stages 121-130.

The adapters connect real in-repository interfaces but deliberately require
injected evidence producers for each specialist role. They do not invent
model output, execute generated code, grant permissions, or activate agents.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .agent_collaboration_pipeline import (
    AgentCollaborationPipeline,
    CollaborationPacket,
    CollaborationRoles,
    CollaborationStage,
    HandoffEvidence,
)
from .agent_factory import AgentCreationRecord, AgentFactory
from .ai_factory_orchestrator import (
    AIFactoryOrchestrator,
    CapabilityGapRequest,
    CandidateFactory,
    CollaborationRunner,
)
from .capability_gap_discovery import CapabilityGap, CapabilityGapArchitect


@dataclass(frozen=True)
class RoleEvidenceInput:
    agent: str
    summary: str
    content: str
    observations: tuple[str, ...]
    passed: bool | None = None
    approved: bool | None = None
    blockers: tuple[str, ...] = ()


RoleEvidenceProducer = Callable[[CapabilityGapRequest, CollaborationStage], RoleEvidenceInput]


class Stage123EvidenceRunner(CollaborationRunner):
    """Drive Stage 123 with separately injected evidence producers."""

    def __init__(
        self,
        *,
        roles: CollaborationRoles,
        producers: Mapping[CollaborationStage, RoleEvidenceProducer],
        pipeline: AgentCollaborationPipeline | None = None,
    ) -> None:
        required = {
            CollaborationStage.DESIGN,
            CollaborationStage.BUILD,
            CollaborationStage.TEST,
            CollaborationStage.REVIEW,
        }
        if set(producers) != required:
            raise ValueError("exactly four stage evidence producers are required")
        if len({roles.architect, roles.builder, roles.tester, roles.reviewer}) != 4:
            raise ValueError("collaboration roles must be independent")
        self.roles = roles
        self.producers = dict(producers)
        self.pipeline = pipeline or AgentCollaborationPipeline()

    def collaborate(self, gap: CapabilityGapRequest) -> CollaborationPacket:
        packet = self.pipeline.create(
            collaboration_id=f"stage123-{gap.gap_id}",
            task=f"{gap.capability}: {gap.description}; evidence: {' | '.join(gap.evidence)}",
            roles=self.roles,
        )
        for stage in (
            CollaborationStage.DESIGN,
            CollaborationStage.BUILD,
            CollaborationStage.TEST,
            CollaborationStage.REVIEW,
        ):
            produced = self.producers[stage](gap, stage)
            if not isinstance(produced, RoleEvidenceInput):
                raise TypeError(f"{stage.value} producer must return RoleEvidenceInput")
            evidence = HandoffEvidence(
                evidence_id=f"{gap.gap_id}-{stage.value}",
                stage=stage,
                agent=produced.agent,
                summary=produced.summary,
                content=produced.content,
                observations=produced.observations,
                passed=produced.passed,
                approved=produced.approved,
                blockers=produced.blockers,
            )
            packet = self.pipeline.advance(packet, evidence)
            if packet.current_stage in (CollaborationStage.BLOCKED, CollaborationStage.COMPLETE):
                break
        return packet


class Stage121FactoryAdapter(CandidateFactory):
    """Bind a Stage 122 gap to the Stage 121 architect and create an inert candidate."""

    def __init__(self, *, factory: AgentFactory, gap_architect: CapabilityGapArchitect) -> None:
        self.factory = factory
        self.gap_architect = gap_architect

    def create_for_gap(self, gap: CapabilityGap) -> AgentCreationRecord:
        gap_id = self.gap_architect.bind(gap)
        return self.create_candidate(gap_id)

    def create_candidate(self, capability_gap: str) -> AgentCreationRecord:
        # The AgentFactory was constructed with this same CapabilityGapArchitect.
        if self.factory.architect is not self.gap_architect:
            raise ValueError("Stage 121 factory must use the supplied CapabilityGapArchitect")
        return self.factory.create_candidate(capability_gap)


class Stage131AIFactory:
    """End-to-end bridge from a Stage 122 gap to a human-gated candidate proposal."""

    def __init__(
        self,
        *,
        gap_architect: CapabilityGapArchitect,
        factory_adapter: Stage121FactoryAdapter,
        collaboration: Stage123EvidenceRunner,
        orchestrator: AIFactoryOrchestrator,
    ) -> None:
        if factory_adapter.gap_architect is not gap_architect:
            raise ValueError("gap architect adapter mismatch")
        if orchestrator.factory is not factory_adapter:
            raise ValueError("orchestrator must use the Stage 121 factory adapter")
        if orchestrator.collaboration is not collaboration:
            raise ValueError("orchestrator must use the Stage 123 evidence runner")
        self.gap_architect = gap_architect
        self.factory_adapter = factory_adapter
        self.collaboration = collaboration
        self.orchestrator = orchestrator

    def propose(self, gap: CapabilityGap) -> object:
        """Return an awaiting-human-approval candidate or a fail-closed result."""
        try:
            request = CapabilityGapRequest(
                gap_id=gap.gap_id,
                capability=gap.capability,
                description=gap.requirement.description,
                evidence=tuple(gap.evidence),
            )
            self.gap_architect.bind(gap)
            return self.orchestrator.process_gap(request)
        except Exception as exc:
            from .ai_factory_orchestrator import FactoryStage, OrchestrationResult
            return OrchestrationResult(
                gap_id=getattr(gap, "gap_id", ""),
                stage=FactoryStage.ORCHESTRATE,
                blocked_reason=f"{type(exc).__name__}: {exc}",
            )


__all__ = [
    "RoleEvidenceInput",
    "RoleEvidenceProducer",
    "Stage123EvidenceRunner",
    "Stage121FactoryAdapter",
    "Stage131AIFactory",
]
