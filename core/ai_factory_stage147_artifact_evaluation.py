"""Stage 147: local artifact preflight and independent merge evaluation contract.

This stage validates supplied local bytes through an injected reader and defines
an immutable before/after evaluation gate. It never opens arbitrary paths,
downloads models, performs tensor operations, runs inference, or activates a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from pathlib import PurePosixPath
from typing import Iterable

from .ai_factory_stage141_evolution import Fitness, dominates
from .ai_factory_stage146_merge_strategy import MergeRecipe, MergeReadiness


_HEX = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024 * 1024


class ArtifactPreflightError(ValueError):
    """Raised when a local artifact manifest or its bytes cannot be trusted."""


class MergeEvaluationError(ValueError):
    """Raised when before/after evaluation evidence is not comparable."""


@dataclass(frozen=True)
class ArtifactManifest:
    model_id: str
    artifact_digest: str
    byte_length: int
    artifact_format: str
    architecture: str
    tokenizer_fingerprint: str
    tensor_schema_fingerprint: str
    quantization: str
    license_id: str
    provenance: str
    local_relative_path: str
    adapter_base_fingerprint: str = ""


@dataclass(frozen=True)
class VerifiedArtifact:
    model_id: str
    artifact_digest: str
    byte_length: int
    manifest_digest: str


def _safe_relative_path(value: str) -> bool:
    if not isinstance(value, str) or not value or chr(92) in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts)


def _manifest_digest(manifest: ArtifactManifest) -> str:
    fields = (
        manifest.model_id, manifest.artifact_digest, str(manifest.byte_length),
        manifest.artifact_format, manifest.architecture, manifest.tokenizer_fingerprint,
        manifest.tensor_schema_fingerprint, manifest.quantization, manifest.license_id,
        manifest.provenance, manifest.local_relative_path, manifest.adapter_base_fingerprint,
    )
    return hashlib.sha256("\\0".join(fields).encode("utf-8")).hexdigest()


def verify_local_artifact(
    manifest: ArtifactManifest,
    chunks: Iterable[bytes],
    *,
    max_bytes: int = _MAX_ARTIFACT_BYTES,
) -> VerifiedArtifact:
    """Verify bytes supplied by a trusted local reader; no path is opened here."""
    if not isinstance(manifest, ArtifactManifest):
        raise ArtifactPreflightError("typed artifact manifest is required")
    if not manifest.model_id.strip() or not manifest.architecture.strip():
        raise ArtifactPreflightError("model identity and architecture are required")
    if not _HEX.fullmatch(manifest.artifact_digest or ""):
        raise ArtifactPreflightError("artifact digest must be lowercase SHA-256")
    if not _safe_relative_path(manifest.local_relative_path):
        raise ArtifactPreflightError("artifact path must be a safe relative path without traversal")
    if not all(value.strip() for value in (
        manifest.artifact_format, manifest.tokenizer_fingerprint,
        manifest.tensor_schema_fingerprint, manifest.quantization,
        manifest.license_id, manifest.provenance,
    )):
        raise ArtifactPreflightError("format, compatibility, license and provenance metadata are required")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ArtifactPreflightError("max_bytes must be a positive integer")
    if (not isinstance(manifest.byte_length, int) or isinstance(manifest.byte_length, bool)
            or manifest.byte_length <= 0 or manifest.byte_length > max_bytes):
        raise ArtifactPreflightError("artifact byte length is outside the configured bound")

    digest = hashlib.sha256()
    total = 0
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ArtifactPreflightError("artifact reader must yield bytes")
            total += len(chunk)
            if total > max_bytes or total > manifest.byte_length:
                raise ArtifactPreflightError("artifact stream exceeded declared or configured byte length")
            digest.update(chunk)
    except ArtifactPreflightError:
        raise
    except Exception as exc:
        raise ArtifactPreflightError(f"artifact reader failed: {exc}") from exc
    if total != manifest.byte_length:
        raise ArtifactPreflightError("artifact byte length does not match manifest")
    actual = digest.hexdigest()
    if actual != manifest.artifact_digest:
        raise ArtifactPreflightError("artifact content digest does not match manifest")
    return VerifiedArtifact(manifest.model_id, actual, total, _manifest_digest(manifest))


@dataclass(frozen=True)
class ArtifactPreflightReport:
    candidate_id: str
    recipe_digest: str
    parent_manifest_digests: tuple[str, ...]
    verified_parents: tuple[VerifiedArtifact, ...]
    ready_for_separate_merge_approval: bool
    reasons: tuple[str, ...]


def preflight_merge_inputs(
    recipe: MergeRecipe,
    manifests: tuple[ArtifactManifest, ...],
    verified: tuple[VerifiedArtifact, ...],
) -> ArtifactPreflightReport:
    """Bind a Stage 146 recipe to independently byte-verified immutable parents."""
    if not isinstance(recipe, MergeRecipe):
        raise ArtifactPreflightError("Stage 146 merge recipe is required")
    if recipe.readiness is not MergeReadiness.PROPOSAL_ONLY:
        raise ArtifactPreflightError("only a tensor/adapter proposal can enter artifact preflight")
    if len(manifests) != len(recipe.parent_ids) or len(verified) != len(manifests):
        raise ArtifactPreflightError("one manifest and byte verification per recipe parent is required")
    for index, (manifest, proof) in enumerate(zip(manifests, verified)):
        if manifest.model_id != recipe.parent_ids[index]:
            raise ArtifactPreflightError("manifest parent order/identity differs from merge recipe")
        if manifest.artifact_digest != recipe.parent_artifact_digests[index]:
            raise ArtifactPreflightError("manifest parent digest differs from authenticated recipe")
        if proof.model_id != manifest.model_id or proof.artifact_digest != manifest.artifact_digest:
            raise ArtifactPreflightError("byte verification does not bind to the supplied manifest")
        if proof.byte_length != manifest.byte_length or proof.manifest_digest != _manifest_digest(manifest):
            raise ArtifactPreflightError("byte verification proof does not bind to the exact manifest")
    first = manifests[0]
    compatibility = ("artifact_format", "architecture", "tokenizer_fingerprint",
                     "tensor_schema_fingerprint", "quantization", "license_id")
    if any(any(getattr(item, field) != getattr(first, field) for field in compatibility)
           for item in manifests[1:]):
        raise ArtifactPreflightError("parent manifests are incompatible for parameter merging")
    if any(not item.provenance.strip() for item in manifests):
        raise ArtifactPreflightError("parent provenance is missing")
    recipe_digest = hashlib.sha256(repr(recipe).encode("utf-8")).hexdigest()
    return ArtifactPreflightReport(
        recipe.candidate_id, recipe_digest,
        tuple(item.manifest_digest for item in verified), verified, True,
        ("all parent bytes match their SHA-256 manifests",
         "output must be written to a new immutable artifact; parent paths must never be overwritten",
         "this preflight does not execute a merge or authorize one"),
    )


@dataclass(frozen=True)
class MergeEvaluation:
    model_id: str
    artifact_digest: str
    suite_digest: str
    evaluator_id: str
    evaluator_model_id: str
    fitness: Fitness


@dataclass(frozen=True)
class MergeEvaluationReport:
    candidate_id: str
    decision: str
    candidate_dominates_parent_count: int
    parent_count: int
    candidate_artifact_digest: str
    suite_digest: str
    reasons: tuple[str, ...]


def evaluate_merge_candidate(
    recipe: MergeRecipe,
    parent_baselines: tuple[MergeEvaluation, ...],
    candidate_result: MergeEvaluation,
    *,
    builder_model_id: str,
    minimum_safety: float = 0.95,
    max_resource_ratio: float = 1.10,
) -> MergeEvaluationReport:
    """Compare independent post-merge evidence against frozen parent baselines."""
    if not isinstance(recipe, MergeRecipe) or recipe.readiness is not MergeReadiness.PROPOSAL_ONLY:
        raise MergeEvaluationError("approved tensor/adapter proposal is required")
    if len(parent_baselines) != len(recipe.parent_ids) or not parent_baselines:
        raise MergeEvaluationError("one frozen baseline per parent is required")
    if not isinstance(candidate_result, MergeEvaluation):
        raise MergeEvaluationError("typed candidate evaluation is required")
    suite = candidate_result.suite_digest
    if not _HEX.fullmatch(suite or "") or suite != recipe.evidence_suite_digest:
        raise MergeEvaluationError("candidate evaluation suite differs from authenticated recipe suite")
    if candidate_result.model_id != recipe.candidate_id:
        raise MergeEvaluationError("candidate evaluation identity differs from recipe")
    if not _HEX.fullmatch(candidate_result.artifact_digest or ""):
        raise MergeEvaluationError("candidate artifact digest is invalid")
    if candidate_result.artifact_digest in recipe.parent_artifact_digests:
        raise MergeEvaluationError("candidate output must be a new artifact, never a parent artifact")
    if not builder_model_id or candidate_result.evaluator_model_id == builder_model_id:
        raise MergeEvaluationError("evaluator must be independent from the merge builder")
    if candidate_result.evaluator_model_id in recipe.parent_ids:
        raise MergeEvaluationError("evaluator must not be one of the parent models")
    if not candidate_result.evaluator_id.strip():
        raise MergeEvaluationError("independent evaluator identity is required")

    if len({item.evaluator_id for item in parent_baselines}) != 1:
        raise MergeEvaluationError("parent baselines must use the same independent evaluator")
    evaluator_id = parent_baselines[0].evaluator_id
    if candidate_result.evaluator_id != evaluator_id:
        raise MergeEvaluationError("before/after evaluator identity must remain unchanged")
    comparisons = []
    for index, (baseline, expected_id, expected_digest) in enumerate(zip(
        parent_baselines, recipe.parent_ids, recipe.parent_artifact_digests
    )):
        if baseline.model_id != expected_id or baseline.artifact_digest != expected_digest:
            raise MergeEvaluationError("parent baseline does not bind to exact recipe parent")
        if baseline.suite_digest != suite or baseline.evaluator_id != evaluator_id:
            raise MergeEvaluationError("parent and candidate evaluations must share suite and evaluator")
        if baseline.evaluator_model_id in recipe.parent_ids or baseline.evaluator_model_id == builder_model_id:
            raise MergeEvaluationError("parent baseline evaluator is not independent")
        comparisons.append(baseline.fitness)

    if candidate_result.fitness.evaluation_suite_digest != suite or any(
        item.evaluation_suite_digest != suite for item in comparisons
    ):
        raise MergeEvaluationError("fitness metrics are not bound to the frozen evaluation suite")
    if candidate_result.fitness.safety < minimum_safety or candidate_result.fitness.regression_count != 0:
        return MergeEvaluationReport(recipe.candidate_id, "BLOCKED", 0, len(comparisons),
            candidate_result.artifact_digest, suite,
            ("absolute safety or regression gate failed",))
    for baseline in comparisons:
        if (candidate_result.fitness.latency_ms / baseline.latency_ms > max_resource_ratio
                or candidate_result.fitness.memory_mb / baseline.memory_mb > max_resource_ratio):
            return MergeEvaluationReport(recipe.candidate_id, "BLOCKED", 0, len(comparisons),
                candidate_result.artifact_digest, suite,
                ("latency or memory regression exceeded the resource guardrail",))
        if candidate_result.fitness.safety < baseline.safety - 0.005:
            return MergeEvaluationReport(recipe.candidate_id, "BLOCKED", 0, len(comparisons),
                candidate_result.artifact_digest, suite,
                ("safety regression exceeded the guardrail",))
    wins = sum(1 for baseline in comparisons if dominates(candidate_result.fitness, baseline))
    if wins == 0:
        return MergeEvaluationReport(recipe.candidate_id, "NO_IMPROVEMENT", 0, len(comparisons),
            candidate_result.artifact_digest, suite,
            ("candidate did not Pareto-dominate any frozen parent baseline",))
    return MergeEvaluationReport(recipe.candidate_id, "IMPROVED", wins, len(comparisons),
        candidate_result.artifact_digest, suite,
        ("independent before/after evaluation passed", "human approval remains mandatory",
         "no model activation or production switch is performed"))


__all__ = [
    "ArtifactManifest", "VerifiedArtifact", "ArtifactPreflightReport",
    "ArtifactPreflightError", "MergeEvaluation", "MergeEvaluationReport",
    "MergeEvaluationError", "verify_local_artifact", "preflight_merge_inputs",
    "evaluate_merge_candidate",
]
