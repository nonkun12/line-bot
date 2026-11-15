"""Stage 142: immutable model lineage and independent evaluation evidence.

This is an in-memory metadata/evidence layer. It does not download, load, edit,
merge, or activate model artifacts and does not perform live inference.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from threading import RLock
from typing import Mapping, Sequence

from .ai_factory_stage141_evolution import (
    CandidateStatus,
    Fitness,
    ModelCandidate,
    ModelDescriptor,
)


_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class EvaluationEvidence:
    candidate_id: str
    evaluated_artifact_digest: str
    evaluation_suite_digest: str
    evaluator_id: str
    fitness: Fitness
    passed: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        for name in ("candidate_id", "evaluator_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise ValueError(f"{name} is invalid")
        for name in ("evaluated_artifact_digest", "evaluation_suite_digest", "evidence_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX_64.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.fitness, Fitness):
            raise TypeError("fitness must be independently measured Fitness")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be boolean")
        if self.fitness.evaluation_suite_digest != self.evaluation_suite_digest:
            raise ValueError("fitness and evidence evaluation-suite digests differ")


@dataclass(frozen=True)
class ModelLineageRecord:
    candidate_id: str
    parent_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    strategy: str
    generation: int
    evaluated_artifact_digest: str
    evaluation_suite_digest: str
    evaluator_id: str
    evidence_digest: str
    status: CandidateStatus = CandidateStatus.PENDING_HUMAN_APPROVAL
    enabled: bool = False


def evidence_digest(
    *, candidate_id: str, evaluated_artifact_digest: str,
    evaluation_suite_digest: str, evaluator_id: str, fitness: Fitness,
) -> str:
    """Canonical digest helper for an evaluator's signed-off result payload."""
    payload = {
        "candidate_id": candidate_id,
        "evaluated_artifact_digest": evaluated_artifact_digest,
        "evaluation_suite_digest": evaluation_suite_digest,
        "evaluator_id": evaluator_id,
        "fitness": {
            "accuracy": fitness.accuracy,
            "instruction_following": fitness.instruction_following,
            "safety": fitness.safety,
            "latency_ms": fitness.latency_ms,
            "memory_mb": fitness.memory_mb,
            "regression_count": fitness.regression_count,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvaluationEvidenceAdapter:
    """Strictly parse a trusted evaluator payload; never calls a model or endpoint."""

    _FIELDS = {
        "candidate_id", "evaluated_artifact_digest", "evaluation_suite_digest",
        "evaluator_id", "accuracy", "instruction_following", "safety",
        "latency_ms", "memory_mb", "regression_count", "passed",
    }

    def ingest(self, payload: Mapping[str, object]) -> EvaluationEvidence:
        if not isinstance(payload, Mapping) or set(payload) != self._FIELDS:
            raise ValueError("evaluation payload must match the exact evidence schema")
        try:
            fitness = Fitness(
                accuracy=payload["accuracy"],
                instruction_following=payload["instruction_following"],
                safety=payload["safety"],
                latency_ms=payload["latency_ms"],
                memory_mb=payload["memory_mb"],
                regression_count=payload["regression_count"],
                evaluation_suite_digest=payload["evaluation_suite_digest"],
            )
            candidate_id = payload["candidate_id"]
            artifact_digest = payload["evaluated_artifact_digest"]
            suite_digest = payload["evaluation_suite_digest"]
            evaluator_id = payload["evaluator_id"]
            passed = payload["passed"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("evaluation payload contains invalid metric or identity fields") from exc
        digest = evidence_digest(
            candidate_id=candidate_id,
            evaluated_artifact_digest=artifact_digest,
            evaluation_suite_digest=suite_digest,
            evaluator_id=evaluator_id,
            fitness=fitness,
        )
        return EvaluationEvidence(
            candidate_id=candidate_id,
            evaluated_artifact_digest=artifact_digest,
            evaluation_suite_digest=suite_digest,
            evaluator_id=evaluator_id,
            fitness=fitness,
            passed=passed,
            evidence_digest=digest,
        )


class ModelLineageRegistry:
    """Bounded, append-only in-memory lineage registry; no approval or activation API."""

    def __init__(self, *, max_records: int = 128) -> None:
        if not isinstance(max_records, int) or not 1 <= max_records <= 1024:
            raise ValueError("max_records must be between 1 and 1024")
        self._max_records = max_records
        self._records: dict[str, ModelLineageRecord] = {}
        self._lock = RLock()

    def record(
        self,
        candidate: ModelCandidate,
        parents: Sequence[ModelDescriptor],
        evidence: EvaluationEvidence,
        *,
        parent_generations: Mapping[str, int] | None = None,
    ) -> ModelLineageRecord:
        if not isinstance(candidate, ModelCandidate):
            raise TypeError("candidate must be a Stage 141 ModelCandidate")
        if not isinstance(evidence, EvaluationEvidence):
            raise TypeError("independent EvaluationEvidence is required")
        if candidate.status is not CandidateStatus.PENDING_HUMAN_APPROVAL or candidate.enabled:
            raise PermissionError("only disabled pending candidates may enter lineage")
        if evidence.passed is not True:
            raise PermissionError("evaluation evidence did not pass")
        if evidence.candidate_id != candidate.candidate_id:
            raise ValueError("evaluation evidence belongs to another candidate")
        if evidence.fitness != candidate.fitness:
            raise ValueError("evaluation fitness differs from the planner fitness")
        parent_tuple = tuple(parents)
        if not 2 <= len(parent_tuple) <= 4 or any(not isinstance(p, ModelDescriptor) for p in parent_tuple):
            raise ValueError("2-4 valid parent model descriptors are required")
        parent_ids = tuple(p.model_id for p in parent_tuple)
        if parent_ids != candidate.parent_ids:
            raise ValueError("parent descriptors do not match candidate lineage")
        if evidence.evaluator_id in parent_ids:
            raise PermissionError("evaluator identity must be independent of parent models")
        generations = dict(parent_generations or {})
        if set(generations) - set(parent_ids):
            raise ValueError("parent generation map contains unknown parent IDs")
        if any(not isinstance(v, int) or v < 0 for v in generations.values()):
            raise ValueError("parent generations must be non-negative integers")
        expected_generation = max((generations.get(pid, 0) for pid in parent_ids), default=0) + 1
        if candidate.generation != expected_generation:
            raise ValueError("candidate generation does not follow its parent generations")
        expected_evidence_digest = evidence_digest(
            candidate_id=evidence.candidate_id,
            evaluated_artifact_digest=evidence.evaluated_artifact_digest,
            evaluation_suite_digest=evidence.evaluation_suite_digest,
            evaluator_id=evidence.evaluator_id,
            fitness=evidence.fitness,
        )
        if evidence.evidence_digest != expected_evidence_digest:
            raise ValueError("evaluation evidence digest mismatch")
        if candidate.fitness.safety < 0.95 or candidate.fitness.regression_count != 0:
            raise PermissionError("safety or regression gate rejected candidate")
        record = ModelLineageRecord(
            candidate_id=candidate.candidate_id,
            parent_ids=parent_ids,
            parent_artifact_digests=tuple(p.artifact_digest for p in parent_tuple),
            strategy=candidate.strategy.value,
            generation=candidate.generation,
            evaluated_artifact_digest=evidence.evaluated_artifact_digest,
            evaluation_suite_digest=evidence.evaluation_suite_digest,
            evaluator_id=evidence.evaluator_id,
            evidence_digest=evidence.evidence_digest,
        )
        with self._lock:
            existing = self._records.get(record.candidate_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("candidate ID already exists with different lineage")
                return existing
            if len(self._records) >= self._max_records:
                raise OverflowError("lineage registry capacity reached")
            self._records[record.candidate_id] = record
        return record

    def get(self, candidate_id: str) -> ModelLineageRecord | None:
        with self._lock:
            return self._records.get(candidate_id)

    def list_records(self) -> tuple[ModelLineageRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def count(self) -> int:
        with self._lock:
            return len(self._records)


__all__ = [
    "EvaluationEvidence", "ModelLineageRecord", "evidence_digest",
    "EvaluationEvidenceAdapter", "ModelLineageRegistry",
]
