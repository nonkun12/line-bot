"""Stage 141: safe evolutionary model-candidate evaluation and merge planning.

This module creates immutable *proposals* only. It never downloads, edits, merges,
loads, or activates model weights. Parameter merging is eligible only when
architecture, tokenizer, tensor schema, format, provenance and local artifacts
are explicitly compatible; otherwise the candidate is an orchestration proposal.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Iterable, Sequence


class MergeStrategy(str, Enum):
    PARAMETER = "parameter_merge"
    ADAPTER = "adapter_merge"
    ORCHESTRATION = "multi_model_orchestration"


class CandidateStatus(str, Enum):
    PENDING_HUMAN_APPROVAL = "pending_human_approval"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    architecture: str
    tokenizer_fingerprint: str
    tensor_schema_fingerprint: str
    artifact_format: str
    artifact_digest: str
    license_id: str
    provenance: str
    quantization: str = "unknown"
    local_artifact_available: bool = False
    adapter_base_fingerprint: str = ""

    def __post_init__(self) -> None:
        for name in ("model_id", "architecture", "tokenizer_fingerprint",
                     "tensor_schema_fingerprint", "artifact_format",
                     "artifact_digest", "license_id", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError(f"{name} must be a non-empty string of at most 256 chars")
        if not isinstance(self.local_artifact_available, bool):
            raise ValueError("local_artifact_available must be boolean")


@dataclass(frozen=True)
class CompatibilityReport:
    compatible: bool
    strategy: MergeStrategy
    reasons: tuple[str, ...]


def assess_compatibility(
    parents: Sequence[ModelDescriptor], *, requested_strategy: MergeStrategy | None = None
) -> CompatibilityReport:
    if not isinstance(parents, Sequence) or len(parents) < 2 or len(parents) > 4:
        raise ValueError("model merge requires 2-4 parent descriptors")
    if len({p.model_id for p in parents}) != len(parents):
        raise ValueError("parent model IDs must be unique")
    if requested_strategy is MergeStrategy.ORCHESTRATION:
        return CompatibilityReport(True, MergeStrategy.ORCHESTRATION,
                                   ("explicit orchestration proposal; no weight merge",))
    first = parents[0]
    parameter_fields = ("architecture", "tokenizer_fingerprint",
                        "tensor_schema_fingerprint", "artifact_format")
    mismatches = tuple(
        f"incompatible {field}" for field in parameter_fields
        if len({getattr(p, field) for p in parents}) != 1
    )
    if any(not p.local_artifact_available for p in parents):
        mismatches += ("all parent artifacts must be available locally",)
    if len({p.license_id for p in parents}) != 1:
        mismatches += ("license compatibility requires explicit review",)
    if mismatches:
        if requested_strategy in (MergeStrategy.PARAMETER, MergeStrategy.ADAPTER):
            return CompatibilityReport(False, requested_strategy, mismatches)
        return CompatibilityReport(True, MergeStrategy.ORCHESTRATION,
                                    mismatches + ("fallback is orchestration only; no tensors combined",))
    if requested_strategy is MergeStrategy.ADAPTER:
        bases = {p.adapter_base_fingerprint for p in parents}
        if "" in bases or len(bases) != 1:
            return CompatibilityReport(False, MergeStrategy.ADAPTER,
                                       ("adapter parents must share an explicit base fingerprint",))
        return CompatibilityReport(True, MergeStrategy.ADAPTER,
                                   ("shared adapter base and compatible parent metadata",))
    return CompatibilityReport(True, MergeStrategy.PARAMETER,
                               ("architecture, tokenizer, tensor schema, format, local artifacts and license match",))


@dataclass(frozen=True)
class Fitness:
    accuracy: float
    instruction_following: float
    safety: float
    latency_ms: float
    memory_mb: float
    regression_count: int = 0
    evaluation_suite_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("accuracy", "instruction_following", "safety"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        for name in ("latency_ms", "memory_mb"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.regression_count, int) or self.regression_count < 0:
            raise ValueError("regression_count must be a non-negative integer")
        if not isinstance(self.evaluation_suite_digest, str) or not self.evaluation_suite_digest.strip():
            raise ValueError("evaluation_suite_digest is required")


@dataclass(frozen=True)
class EvolutionarySafety:
    kill_switch_active: bool = False
    hold_active: bool = False
    evidence_complete: bool = True
    budget_available: bool = True
    max_candidates_per_tick: int = 2


@dataclass(frozen=True)
class ModelCandidate:
    candidate_id: str
    parent_ids: tuple[str, ...]
    strategy: MergeStrategy
    compatibility: CompatibilityReport
    fitness: Fitness
    generation: int
    status: CandidateStatus = CandidateStatus.PENDING_HUMAN_APPROVAL
    enabled: bool = False


@dataclass(frozen=True)
class EvolutionReport:
    candidates: tuple[ModelCandidate, ...]
    pareto_frontier: tuple[str, ...]
    stopped_reason: str | None = None


def dominates(left: Fitness, right: Fitness) -> bool:
    """Pareto dominance: maximize quality/safety, minimize latency/memory/regressions."""
    a = (left.accuracy, left.instruction_following, left.safety,
         -left.latency_ms, -left.memory_mb, -left.regression_count)
    b = (right.accuracy, right.instruction_following, right.safety,
         -right.latency_ms, -right.memory_mb, -right.regression_count)
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def pareto_frontier(candidates: Iterable[ModelCandidate]) -> tuple[str, ...]:
    items = tuple(candidates)
    eligible = tuple(c for c in items if c.status is CandidateStatus.PENDING_HUMAN_APPROVAL
                     and c.fitness.safety >= 0.95 and c.fitness.regression_count == 0)
    return tuple(c.candidate_id for c in eligible
                 if not any(dominates(other.fitness, c.fitness)
                            for other in eligible if other.candidate_id != c.candidate_id))


class EvolutionaryModelMergePlanner:
    """Bounded metadata planner; evaluation results must be supplied independently."""

    def plan(
        self,
        tick_id: str,
        parent_groups: Sequence[Sequence[ModelDescriptor]],
        fitness_results: Sequence[Fitness],
        *,
        safety: EvolutionarySafety = EvolutionarySafety(),
        generation: int = 1,
        requested_strategy: MergeStrategy | None = None,
    ) -> EvolutionReport:
        reason = None
        if safety.kill_switch_active:
            reason = "global kill switch is active"
        elif safety.hold_active:
            reason = "HOLD is active"
        elif not safety.evidence_complete:
            reason = "required evaluation evidence is incomplete"
        elif not safety.budget_available:
            reason = "safe execution budget is unavailable"
        elif not 1 <= safety.max_candidates_per_tick <= 4:
            reason = "max_candidates_per_tick must be between 1 and 4"
        elif not isinstance(generation, int) or generation < 1:
            reason = "generation must be a positive integer"
        if reason:
            return EvolutionReport((), (), reason)
        if len(parent_groups) != len(fitness_results):
            return EvolutionReport((), (), "each candidate requires an independent fitness result")
        if len(parent_groups) > safety.max_candidates_per_tick:
            return EvolutionReport((), (), "candidate limit exceeded")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", tick_id or ""):
            return EvolutionReport((), (), "invalid tick_id")

        candidates = []
        for index, (parents, fitness) in enumerate(zip(parent_groups, fitness_results)):
            try:
                compatibility = assess_compatibility(parents, requested_strategy=requested_strategy)
                if not compatibility.compatible:
                    continue
                if fitness.safety < 0.95 or fitness.regression_count:
                    continue
                parent_ids = tuple(p.model_id for p in parents)
                import hashlib
                raw_id = f"{tick_id}\0{generation}\0{index}\0{'|'.join(parent_ids)}\0{compatibility.strategy.value}\0{fitness.evaluation_suite_digest}"
                candidate_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
                candidates.append(ModelCandidate(candidate_id, parent_ids, compatibility.strategy,
                                                  compatibility, fitness, generation))
            except (TypeError, ValueError):
                continue
        frozen = tuple(candidates)
        return EvolutionReport(frozen, pareto_frontier(frozen),
                               None if frozen else "no candidate passed compatibility and safety gates")


__all__ = [
    "MergeStrategy", "CandidateStatus", "ModelDescriptor", "CompatibilityReport",
    "assess_compatibility", "Fitness", "EvolutionarySafety", "ModelCandidate",
    "EvolutionReport", "dominates", "pareto_frontier", "EvolutionaryModelMergePlanner",
]
