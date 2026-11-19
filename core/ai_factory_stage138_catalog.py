"""Metadata-only candidate catalog with a hard human-approval boundary."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib
from threading import RLock
from .agent_factory import AgentCreationRecord
from .agent_specs import AgentLifecycle


class CandidateStatus(str, Enum):
    PENDING_HUMAN_APPROVAL = "pending_human_approval"


@dataclass(frozen=True)
class PendingAgentCandidate:
    candidate_id: str
    agent_name: str
    purpose: str
    spec_digest: str
    artifact_digest: str
    artifact_paths: tuple[str, ...]
    test_evidence: tuple[str, ...]
    review_findings: tuple[str, ...]
    status: CandidateStatus = CandidateStatus.PENDING_HUMAN_APPROVAL
    enabled: bool = False


class PendingAgentCatalog:
    """Store only hashes/metadata; never stores executable artifacts or enables agents."""
    def __init__(self) -> None:
        self._items: dict[str, PendingAgentCandidate] = {}
        self._lock = RLock()

    @staticmethod
    def _digests(record: AgentCreationRecord) -> tuple[str, str]:
        spec = record.build.spec
        spec_payload = "\0".join((
            spec.name, spec.purpose, spec.input_contract, spec.output_contract,
            *spec.allowed_tools, *spec.resource_scope, *spec.safety_constraints, *spec.tests,
        ))
        spec_digest = hashlib.sha256(spec_payload.encode("utf-8")).hexdigest()
        artifact = hashlib.sha256()
        for item in sorted(record.build.files, key=lambda value: value.path):
            artifact.update(item.path.encode("utf-8")); artifact.update(b"\0")
            artifact.update(item.content.encode("utf-8")); artifact.update(b"\0")
        return spec_digest, artifact.hexdigest()

    def submit(self, record: AgentCreationRecord) -> PendingAgentCandidate:
        if not isinstance(record, AgentCreationRecord):
            raise TypeError("candidate catalog accepts only AgentCreationRecord")
        spec = record.build.spec
        if record.lifecycle is not AgentLifecycle.REVIEWED or spec.lifecycle is not AgentLifecycle.REVIEWED:
            raise PermissionError("only REVIEWED candidates may be submitted")
        if not record.tests.passed or not record.tests.evidence or record.tests.failures:
            raise PermissionError("passing sandbox evidence is required")
        if not record.review.approved or record.review.blockers:
            raise PermissionError("independent review approval is required")
        if spec.allowed_tools or spec.resource_scope:
            raise PermissionError("Stage 138 catalog accepts zero-privilege candidates only")
        if not spec.safety_constraints or not spec.tests:
            raise ValueError("safety constraints and validation tests are required")
        spec_digest, artifact_digest = self._digests(record)
        candidate_id = hashlib.sha256(
            f"{spec.name}\0{spec_digest}\0{artifact_digest}".encode("utf-8")
        ).hexdigest()
        candidate = PendingAgentCandidate(
            candidate_id=candidate_id,
            agent_name=spec.name,
            purpose=spec.purpose,
            spec_digest=spec_digest,
            artifact_digest=artifact_digest,
            artifact_paths=tuple(sorted(item.path for item in record.build.files)),
            test_evidence=tuple(record.tests.evidence),
            review_findings=tuple(record.review.findings),
        )
        with self._lock:
            existing = self._items.get(candidate_id)
            if existing is not None:
                if existing != candidate:
                    raise ValueError("candidate ID collision with different metadata")
                return existing
            if any(item.agent_name == candidate.agent_name for item in self._items.values()):
                raise ValueError(f"candidate name already pending: {candidate.agent_name}")
            self._items[candidate_id] = candidate
        return candidate

    def get(self, candidate_id: str) -> PendingAgentCandidate | None:
        with self._lock:
            return self._items.get(str(candidate_id))

    def list_pending(self) -> tuple[PendingAgentCandidate, ...]:
        with self._lock:
            return tuple(self._items.values())

    def count(self) -> int:
        with self._lock:
            return len(self._items)


__all__ = ["CandidateStatus", "PendingAgentCandidate", "PendingAgentCatalog"]
