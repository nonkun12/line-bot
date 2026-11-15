"""Stage 144: authenticated evidence gate for evolutionary selection.

Only evidence accepted by Stage 143 can enter this bounded in-memory selection
pool. This is a proposal/selection layer only: it never merges or activates
weights, and it does not claim that signed measurements are objectively true.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Sequence

from .ai_factory_stage141_evolution import (
    EvolutionReport,
    Fitness,
    ModelCandidate,
    ModelDescriptor,
    pareto_frontier,
)
from .ai_factory_stage142_lineage import ModelLineageRecord, ModelLineageRegistry
from .ai_factory_stage143_evidence_auth import (
    AuthenticatedEvidenceVerifier,
    EvaluationEvidence,
)


@dataclass(frozen=True)
class AuthenticatedCandidate:
    candidate: ModelCandidate
    evidence_digest: str
    key_id: str
    nonce: str


@dataclass(frozen=True)
class EvolutionSelectionSnapshot:
    accepted_candidate_ids: tuple[str, ...]
    pareto_frontier_ids: tuple[str, ...]
    records: tuple[ModelLineageRecord, ...]
    blocked_reason: str | None = None


class AuthenticatedEvolutionEvidenceStore:
    """Single ingress for authenticated candidates; bounded and fail-closed."""

    def __init__(
        self,
        verifier: AuthenticatedEvidenceVerifier,
        *,
        max_candidates: int = 64,
    ) -> None:
        if not isinstance(verifier, AuthenticatedEvidenceVerifier):
            raise TypeError("Stage 143 AuthenticatedEvidenceVerifier is required")
        if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or not 1 <= max_candidates <= 128:
            raise ValueError("max_candidates must be between 1 and 128")
        self._verifier = verifier
        self._registry = ModelLineageRegistry(max_records=max_candidates)
        self._max_candidates = max_candidates
        self._accepted: dict[str, AuthenticatedCandidate] = {}
        self._lock = RLock()

    def accept(
        self,
        candidate: ModelCandidate,
        parents: Sequence[ModelDescriptor],
        evidence: EvaluationEvidence,
        *,
        key_id: str,
        nonce: str,
        signature_hex: str,
        expected_artifact_digest: str,
        expected_suite_digest: str,
        parent_generations: dict[str, int] | None = None,
    ) -> ModelLineageRecord:
        if not isinstance(candidate, ModelCandidate):
            raise TypeError("Stage 141 ModelCandidate is required")
        if candidate.candidate_id in self._accepted:
            raise ValueError("candidate already accepted into this evolution pool")
        if evidence.fitness != candidate.fitness:
            raise ValueError("candidate fitness does not match signed evaluation evidence")
        # Verify before lineage insertion. Verification consumes the nonce; any later
        # validation failure is deliberately fail-closed and requires fresh evidence.
        verified = self._verifier.verify(
            evidence,
            key_id=key_id,
            nonce=nonce,
            signature_hex=signature_hex,
            expected_candidate_id=candidate.candidate_id,
            expected_artifact_digest=expected_artifact_digest,
            expected_suite_digest=expected_suite_digest,
        )
        with self._lock:
            if candidate.candidate_id in self._accepted:
                raise ValueError("candidate already accepted into this evolution pool")
            if len(self._accepted) >= self._max_candidates:
                raise OverflowError("evolution candidate capacity reached; refusing new candidates")
            record = self._registry.record(
                candidate, parents, verified, parent_generations=parent_generations
            )
            self._accepted[candidate.candidate_id] = AuthenticatedCandidate(
                candidate=candidate,
                evidence_digest=verified.evidence_digest,
                key_id=key_id,
                nonce=nonce,
            )
            return record

    def snapshot(self) -> EvolutionSelectionSnapshot:
        with self._lock:
            candidates = tuple(item.candidate for item in self._accepted.values())
            frontier = pareto_frontier(candidates)
            return EvolutionSelectionSnapshot(
                accepted_candidate_ids=tuple(self._accepted),
                pareto_frontier_ids=frontier,
                records=self._registry.list_records(),
            )

    def get(self, candidate_id: str) -> AuthenticatedCandidate | None:
        with self._lock:
            return self._accepted.get(candidate_id)

    def count(self) -> int:
        with self._lock:
            return len(self._accepted)


__all__ = [
    "AuthenticatedCandidate", "EvolutionSelectionSnapshot",
    "AuthenticatedEvolutionEvidenceStore",
]
