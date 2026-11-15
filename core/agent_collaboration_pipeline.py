"""Evidence-backed, immutable multi-agent collaboration pipeline.

This module coordinates design -> build -> test -> independent review. It
records handoff evidence but never executes generated code, grants permissions,
writes repository files, or activates agents.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
from typing import Mapping


class CollaborationStage(str, Enum):
    DESIGN = "design"
    BUILD = "build"
    TEST = "test"
    REVIEW = "review"
    COMPLETE = "complete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CollaborationRoles:
    architect: str
    builder: str
    tester: str
    reviewer: str

    def validate(self) -> tuple[str, ...]:
        values = (self.architect, self.builder, self.tester, self.reviewer)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            return ("all collaboration roles must be named",)
        if len({value.strip().casefold() for value in values}) != len(values):
            return ("collaboration roles must use independent agents",)
        return ()


@dataclass(frozen=True)
class HandoffEvidence:
    evidence_id: str
    stage: CollaborationStage
    agent: str
    summary: str
    content: str
    observations: tuple[str, ...]
    passed: bool | None = None
    approved: bool | None = None
    blockers: tuple[str, ...] = ()

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.evidence_id.strip():
            errors.append("evidence_id is required")
        if not self.agent.strip():
            errors.append("evidence agent is required")
        if not self.summary.strip():
            errors.append("evidence summary is required")
        if not self.content.strip():
            errors.append("evidence content is required")
        if not self.observations or any(not item.strip() for item in self.observations):
            errors.append("non-empty evidence observations are required")
        if self.stage is CollaborationStage.TEST and self.passed is None:
            errors.append("test evidence must explicitly state passed")
        if self.stage is CollaborationStage.REVIEW and self.approved is None:
            errors.append("review evidence must explicitly state approved")
        if self.stage is CollaborationStage.REVIEW and self.approved and self.blockers:
            errors.append("approved review cannot contain blockers")
        return tuple(errors)

    @property
    def content_sha256(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CollaborationPacket:
    collaboration_id: str
    task: str
    roles: CollaborationRoles
    current_stage: CollaborationStage = CollaborationStage.DESIGN
    evidence: tuple[HandoffEvidence, ...] = ()
    safety_constraints: tuple[str, ...] = (
        "least privilege",
        "no permission escalation",
        "no automatic merge",
        "no automatic deployment",
        "human approval required for production activation",
    )
    blocked_reason: str | None = None

    def validate(self) -> tuple[str, ...]:
        errors = list(self.roles.validate())
        if not self.collaboration_id.strip():
            errors.append("collaboration_id is required")
        if not self.task.strip():
            errors.append("task is required")
        if not self.safety_constraints or any(not item.strip() for item in self.safety_constraints):
            errors.append("safety constraints are required")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            errors.append("evidence ids must be unique")
        for item in self.evidence:
            errors.extend(item.validate())
        if self.current_stage is CollaborationStage.BLOCKED and not self.blocked_reason:
            errors.append("blocked packet must include a reason")
        return tuple(errors)

    @property
    def evidence_digests(self) -> tuple[tuple[str, str], ...]:
        return tuple((item.evidence_id, item.content_sha256) for item in self.evidence)


class AgentCollaborationPipeline:
    """Advance an immutable collaboration only with role-matched evidence."""

    _NEXT = {
        CollaborationStage.DESIGN: (CollaborationStage.BUILD, "architect"),
        CollaborationStage.BUILD: (CollaborationStage.TEST, "builder"),
        CollaborationStage.TEST: (CollaborationStage.REVIEW, "tester"),
        CollaborationStage.REVIEW: (CollaborationStage.COMPLETE, "reviewer"),
    }

    def create(self, collaboration_id: str, task: str, roles: CollaborationRoles) -> CollaborationPacket:
        packet = CollaborationPacket(
            collaboration_id=str(collaboration_id).strip(),
            task=str(task).strip(),
            roles=roles,
        )
        errors = packet.validate()
        if errors:
            raise ValueError("invalid collaboration packet: " + "; ".join(errors))
        return packet

    def advance(self, packet: CollaborationPacket, evidence: HandoffEvidence) -> CollaborationPacket:
        errors = packet.validate()
        if errors:
            raise ValueError("invalid collaboration packet: " + "; ".join(errors))
        if packet.current_stage in (CollaborationStage.COMPLETE, CollaborationStage.BLOCKED):
            raise ValueError("terminal collaboration packet cannot advance")
        if not isinstance(evidence, HandoffEvidence):
            raise TypeError("evidence must be HandoffEvidence")
        evidence_errors = evidence.validate()
        if evidence_errors:
            raise ValueError("invalid handoff evidence: " + "; ".join(evidence_errors))
        if evidence.stage is not packet.current_stage:
            raise ValueError("evidence stage does not match current collaboration stage")

        next_stage, role_name = self._NEXT[packet.current_stage]
        expected_agent = getattr(packet.roles, role_name).strip().casefold()
        if evidence.agent.strip().casefold() != expected_agent:
            raise PermissionError(f"only the assigned {role_name} may advance this stage")
        if evidence.evidence_id in {item.evidence_id for item in packet.evidence}:
            raise ValueError("duplicate evidence_id")

        updated_evidence = packet.evidence + (evidence,)
        if packet.current_stage is CollaborationStage.TEST and evidence.passed is not True:
            reason = "test stage failed or did not pass; review is blocked"
            return replace(
                packet,
                current_stage=CollaborationStage.BLOCKED,
                evidence=updated_evidence,
                blocked_reason=reason,
            )
        if packet.current_stage is CollaborationStage.REVIEW:
            if evidence.approved is not True or evidence.blockers:
                reason = "independent review did not approve; activation is blocked"
                return replace(
                    packet,
                    current_stage=CollaborationStage.BLOCKED,
                    evidence=updated_evidence,
                    blocked_reason=reason,
                )
        updated = replace(packet, current_stage=next_stage, evidence=updated_evidence)
        errors = updated.validate()
        if errors:
            raise ValueError("collaboration transition invalid: " + "; ".join(errors))
        return updated


__all__ = [
    "CollaborationStage",
    "CollaborationRoles",
    "HandoffEvidence",
    "CollaborationPacket",
    "AgentCollaborationPipeline",
]
