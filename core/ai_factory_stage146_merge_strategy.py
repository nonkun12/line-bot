"""Stage 146: evidence-bound model merge strategy planning.

Creates immutable, deterministic recipes only. It does not download or read
weights, execute merge algorithms, write artifacts, run inference, or activate
a model. Incompatible model families are routed to orchestration, never forced
into tensor arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Sequence

from .ai_factory_stage141_evolution import ModelDescriptor
from .ai_factory_stage145_improvement_gate import (
    EvolutionDecision,
    GenerationImprovementReport,
)


class MergeMethod(str, Enum):
    SLERP = "slerp"
    TIES = "ties"
    DARE = "dare"
    TASK_ARITHMETIC = "task_arithmetic"
    LORA = "lora_adapter"
    ORCHESTRATION = "multi_model_orchestration"


class MergeReadiness(str, Enum):
    PROPOSAL_ONLY = "proposal_only"
    ORCHESTRATION_ONLY = "orchestration_only"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MergeRecipe:
    candidate_id: str
    generation: int
    method: MergeMethod
    readiness: MergeReadiness
    parent_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    output_artifact_digest: str
    tokenizer_fingerprint: str
    tensor_schema_fingerprint: str
    artifact_format: str
    quantization: str
    coefficients: tuple[float, ...]
    density: float | None
    seed: int
    reasons: tuple[str, ...]
    evidence_suite_digest: str


class MergeRecipeError(ValueError):
    """Raised for malformed or unauthenticated merge recipe inputs."""


_HEX = re.compile(r"^[0-9a-f]{64}$")
_DENSE_FORMATS = {"safetensors", "pytorch"}
_DENSE_DTYPES = {"fp16", "bf16", "fp32"}


class EvolutionaryMergeStrategyPlanner:
    """Builds a merge recipe only from a Stage 145 IMPROVED report."""

    def plan(
        self,
        report: GenerationImprovementReport,
        parents: Sequence[ModelDescriptor],
        *,
        requested_method: MergeMethod | None = None,
        coefficients: Sequence[float] | None = None,
        density: float | None = None,
        seed: int = 0,
    ) -> MergeRecipe:
        if not isinstance(report, GenerationImprovementReport):
            raise MergeRecipeError("Stage 145 generation improvement report is required")
        if report.decision is not EvolutionDecision.IMPROVED or report.lineage_record is None:
            raise MergeRecipeError("only authenticated IMPROVED candidates can receive merge recipes")
        record = report.lineage_record
        if record.candidate_id != report.candidate_id or record.generation != report.generation:
            raise MergeRecipeError("report and immutable lineage identity mismatch")
        if record.enabled or record.status.value != "pending_human_approval":
            raise MergeRecipeError("candidate must remain disabled and pending human approval")
        if not isinstance(parents, Sequence) or not 2 <= len(parents) <= 4:
            raise MergeRecipeError("2-4 parent descriptors are required")
        if any(not isinstance(parent, ModelDescriptor) for parent in parents):
            raise MergeRecipeError("all parent descriptors must be typed ModelDescriptor values")
        parent_ids = tuple(parent.model_id for parent in parents)
        parent_digests = tuple(parent.artifact_digest for parent in parents)
        if parent_ids != record.parent_ids or parent_digests != record.parent_artifact_digests:
            raise MergeRecipeError("parent descriptors do not match authenticated lineage")
        if not _HEX.fullmatch(record.evaluated_artifact_digest or ""):
            raise MergeRecipeError("evaluated candidate artifact digest is invalid")
        if not _HEX.fullmatch(record.evaluation_suite_digest or ""):
            raise MergeRecipeError("evaluation suite digest is invalid")
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**31 - 1:
            raise MergeRecipeError("seed must be a bounded non-negative integer")

        first = parents[0]
        common_fields = ("architecture", "tokenizer_fingerprint",
                         "tensor_schema_fingerprint", "artifact_format", "quantization")
        mismatches = tuple(
            f"parent {field} differs" for field in common_fields
            if len({getattr(parent, field) for parent in parents}) != 1
        )
        if any(not parent.local_artifact_available for parent in parents):
            mismatches += ("one or more parent artifacts are not declared locally available",)
        if len({parent.license_id for parent in parents}) != 1:
            mismatches += ("parent license identifiers differ and require separate legal review",)
        if any(not parent.provenance.strip() for parent in parents):
            mismatches += ("parent provenance is missing",)

        method = requested_method or MergeMethod.SLERP
        dense_compatible = (
            not mismatches
            and first.artifact_format in _DENSE_FORMATS
            and first.quantization in _DENSE_DTYPES
        )
        adapter_compatible = (
            not mismatches
            and first.artifact_format in _DENSE_FORMATS
            and len({parent.adapter_base_fingerprint for parent in parents}) == 1
            and bool(first.adapter_base_fingerprint)
        )

        if method is MergeMethod.ORCHESTRATION:
            readiness = MergeReadiness.ORCHESTRATION_ONLY
            reasons = ("explicit multi-model orchestration proposal; no tensor operations",)
            coefficients_tuple: tuple[float, ...] = ()
            density_value = None
        elif method is MergeMethod.LORA:
            if not adapter_compatible:
                return self._orchestration(report, parents, mismatches + (
                    "LoRA merge requires matching dense adapter base fingerprints and parent metadata",
                ), seed)
            readiness = MergeReadiness.PROPOSAL_ONLY
            reasons = ("adapter base fingerprint and parent metadata match; execution still requires artifact inspection and approval",)
            coefficients_tuple = self._coefficients(coefficients, len(parents))
            density_value = None
        elif not dense_compatible:
            return self._orchestration(report, parents, mismatches + (
                "requested tensor merge requires matching dense architecture, tokenizer, tensor schema, format and quantization",
            ), seed)
        else:
            readiness = MergeReadiness.PROPOSAL_ONLY
            reasons = (
                "parent metadata is compatible for the requested merge family",
                "recipe only: no tensor files were opened or modified",
                "independent post-merge evaluation and human approval remain mandatory",
            )
            coefficients_tuple = self._coefficients(coefficients, len(parents))
            density_value = density
            if method in (MergeMethod.TIES, MergeMethod.DARE):
                if density is None or not isinstance(density, (int, float)) or not math.isfinite(density) or not 0 < density <= 1:
                    raise MergeRecipeError("TIES/DARE density must be finite and in (0, 1]")
            elif density is not None:
                raise MergeRecipeError("density is only valid for TIES or DARE")
            if method is MergeMethod.SLERP and len(parents) != 2:
                raise MergeRecipeError("SLERP currently requires exactly two parent models")

        return MergeRecipe(
            candidate_id=report.candidate_id,
            generation=report.generation,
            method=method,
            readiness=readiness,
            parent_ids=parent_ids,
            parent_artifact_digests=parent_digests,
            output_artifact_digest=record.evaluated_artifact_digest,
            tokenizer_fingerprint=first.tokenizer_fingerprint,
            tensor_schema_fingerprint=first.tensor_schema_fingerprint,
            artifact_format=first.artifact_format,
            quantization=first.quantization,
            coefficients=coefficients_tuple,
            density=density_value,
            seed=seed,
            reasons=reasons,
            evidence_suite_digest=record.evaluation_suite_digest,
        )

    @staticmethod
    def _coefficients(values: Sequence[float] | None, count: int) -> tuple[float, ...]:
        if values is None:
            return tuple(1.0 / count for _ in range(count))
        if not isinstance(values, Sequence) or len(values) != count:
            raise MergeRecipeError("one coefficient per parent is required")
        result = tuple(float(value) for value in values)
        if any(not math.isfinite(value) or value < 0 for value in result):
            raise MergeRecipeError("coefficients must be finite and non-negative")
        if not math.isclose(sum(result), 1.0, rel_tol=0, abs_tol=1e-9):
            raise MergeRecipeError("coefficients must sum to 1.0")
        return result

    def _orchestration(
        self,
        report: GenerationImprovementReport,
        parents: Sequence[ModelDescriptor],
        reasons: tuple[str, ...],
        seed: int,
    ) -> MergeRecipe:
        record = report.lineage_record
        return MergeRecipe(
            candidate_id=report.candidate_id,
            generation=report.generation,
            method=MergeMethod.ORCHESTRATION,
            readiness=MergeReadiness.ORCHESTRATION_ONLY,
            parent_ids=tuple(parent.model_id for parent in parents),
            parent_artifact_digests=tuple(parent.artifact_digest for parent in parents),
            output_artifact_digest=record.evaluated_artifact_digest,
            tokenizer_fingerprint="",
            tensor_schema_fingerprint="",
            artifact_format="",
            quantization="",
            coefficients=(),
            density=None,
            seed=seed,
            reasons=reasons + ("fallback is routing/ensemble only; no weights are combined",),
            evidence_suite_digest=record.evaluation_suite_digest,
        )


__all__ = [
    "MergeMethod", "MergeReadiness", "MergeRecipe", "MergeRecipeError",
    "EvolutionaryMergeStrategyPlanner",
]
