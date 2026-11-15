"""Stage 154: evidence-bound evolutionary model-merge evaluation plans.

This stage plans bounded, reproducible strategy trials from Stage 153 survivors.
It never reads tensors, executes a merge, runs inference, advances generations,
or grants execution/merge/activation authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Sequence

from .ai_factory_stage141_evolution import MergeStrategy, ModelDescriptor, assess_compatibility
from .ai_factory_stage153_generation_model_selection import (
    CandidateModelEvidence, GenerationSelectionReport, SelectionDecision,
)

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class MergeEvaluationPlanError(ValueError):
    """Raised when merge evaluation planning evidence is incomplete or unsafe."""


class MergeAlgorithm(str, Enum):
    SLERP = "slerp"
    TIES = "ties"
    DARE = "dare"
    TASK_ARITHMETIC = "task_arithmetic"
    LORA = "lora"


@dataclass(frozen=True)
class MergeStrategyParameters:
    interpolation: float | None = None
    density: float | None = None
    merge_coefficient: float | None = None
    lora_rank: int | None = None
    lora_alpha: float | None = None


@dataclass(frozen=True)
class MergeEvaluationPlan:
    plan_id: str
    candidate_id: str
    generation: int
    algorithm: MergeAlgorithm
    parameters: MergeStrategyParameters
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    recipe_digest: str
    strategy: str
    independent_evaluation_required: bool = True
    execution_authorized: bool = False
    merge_authorized: bool = False
    activation_authorized: bool = False


@dataclass(frozen=True)
class OrchestrationRoute:
    candidate_id: str
    reasons: tuple[str, ...]
    strategy: str = "multi_model_orchestration"
    weight_merge_proposed: bool = False


@dataclass(frozen=True)
class MergeEvaluationPlanReport:
    evaluation_suite_digest: str
    source_selection_digest: str
    plans: tuple[MergeEvaluationPlan, ...]
    orchestration_routes: tuple[OrchestrationRoute, ...]
    digest: str
    proposal_only: bool = True
    tensors_read: bool = False
    weights_modified: bool = False
    inference_executed: bool = False
    generation_advanced: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _validate_parameters(algorithm: MergeAlgorithm, params: MergeStrategyParameters) -> None:
    if not isinstance(params, MergeStrategyParameters):
        raise MergeEvaluationPlanError("typed strategy parameters are required")
    if algorithm is MergeAlgorithm.SLERP:
        if params.interpolation is None or not math.isfinite(params.interpolation) or not 0 <= params.interpolation <= 1:
            raise MergeEvaluationPlanError("SLERP interpolation must be finite and between 0 and 1")
        if any(x is not None for x in (params.density, params.merge_coefficient, params.lora_rank, params.lora_alpha)):
            raise MergeEvaluationPlanError("SLERP accepts only interpolation")
    elif algorithm is MergeAlgorithm.TIES:
        if params.density is None or not math.isfinite(params.density) or not 0 < params.density <= 1:
            raise MergeEvaluationPlanError("TIES density must be finite and in (0, 1]")
        if params.merge_coefficient is None or not math.isfinite(params.merge_coefficient) or not -2 <= params.merge_coefficient <= 2:
            raise MergeEvaluationPlanError("TIES merge coefficient must be finite and in [-2, 2]")
        if any(x is not None for x in (params.interpolation, params.lora_rank, params.lora_alpha)):
            raise MergeEvaluationPlanError("TIES received unrelated parameters")
    elif algorithm is MergeAlgorithm.DARE:
        if params.density is None or not math.isfinite(params.density) or not 0 < params.density <= 1:
            raise MergeEvaluationPlanError("DARE density must be finite and in (0, 1]")
        if params.merge_coefficient is None or not math.isfinite(params.merge_coefficient) or not -2 <= params.merge_coefficient <= 2:
            raise MergeEvaluationPlanError("DARE merge coefficient must be finite and in [-2, 2]")
        if any(x is not None for x in (params.interpolation, params.lora_rank, params.lora_alpha)):
            raise MergeEvaluationPlanError("DARE received unrelated parameters")
    elif algorithm is MergeAlgorithm.TASK_ARITHMETIC:
        if params.merge_coefficient is None or not math.isfinite(params.merge_coefficient) or not -2 <= params.merge_coefficient <= 2:
            raise MergeEvaluationPlanError("task arithmetic coefficient must be finite and in [-2, 2]")
        if any(x is not None for x in (params.interpolation, params.density, params.lora_rank, params.lora_alpha)):
            raise MergeEvaluationPlanError("task arithmetic received unrelated parameters")
    elif algorithm is MergeAlgorithm.LORA:
        if not isinstance(params.lora_rank, int) or isinstance(params.lora_rank, bool) or not 1 <= params.lora_rank <= 256:
            raise MergeEvaluationPlanError("LoRA rank must be an integer between 1 and 256")
        if params.lora_alpha is None or not math.isfinite(params.lora_alpha) or not 0 < params.lora_alpha <= 512:
            raise MergeEvaluationPlanError("LoRA alpha must be finite and in (0, 512]")
        if any(x is not None for x in (params.interpolation, params.density, params.merge_coefficient)):
            raise MergeEvaluationPlanError("LoRA received unrelated parameters")


class EvolutionaryMergeEvaluationPlanner:
    """Create deterministic, bounded plans; external independent evaluation is required."""

    def __init__(self, *, max_plans: int = 16) -> None:
        if not isinstance(max_plans, int) or isinstance(max_plans, bool) or not 1 <= max_plans <= 64:
            raise ValueError("max_plans must be an integer between 1 and 64")
        self._max_plans = max_plans

    def plan(
        self,
        selection: GenerationSelectionReport,
        candidates: Sequence[CandidateModelEvidence],
        *,
        expected_suite_digest: str,
        parameter_grid: Sequence[tuple[MergeAlgorithm, MergeStrategyParameters]] | None = None,
        kill_switch_active: bool = False,
        hold_active: bool = False,
        budget_available: bool = True,
    ) -> MergeEvaluationPlanReport:
        if kill_switch_active or hold_active or not budget_available:
            raise MergeEvaluationPlanError("kill switch, HOLD, or unavailable budget blocks planning")
        if not isinstance(selection, GenerationSelectionReport) or not selection.proposal_only:
            raise MergeEvaluationPlanError("proposal-only Stage 153 selection report is required")
        if not _valid_digest(expected_suite_digest) or selection.evaluation_suite_digest != expected_suite_digest:
            raise MergeEvaluationPlanError("frozen evaluation suite digest drift")
        if not _valid_digest(selection.digest):
            raise MergeEvaluationPlanError("source selection digest is invalid")
        if not isinstance(candidates, Sequence) or not candidates:
            raise MergeEvaluationPlanError("typed Stage 153 candidate evidence is required")
        by_id = {}
        for item in candidates:
            if not isinstance(item, CandidateModelEvidence):
                raise MergeEvaluationPlanError("typed candidate evidence is required")
            cid = item.entry.candidate_id
            if cid in by_id:
                raise MergeEvaluationPlanError("duplicate candidate evidence")
            by_id[cid] = item
        selected = {x.candidate_id for x in selection.selections if x.decision is SelectionDecision.SELECTED}
        if selected != set(selection.survivor_candidate_ids) or not selected.issubset(by_id):
            raise MergeEvaluationPlanError("survivor set does not match supplied exact candidate evidence")
        if set(by_id) != {x.candidate_id for x in selection.selections}:
            raise MergeEvaluationPlanError("candidate evidence must cover the exact Stage 153 selection set")

        grid = tuple(parameter_grid) if parameter_grid is not None else (
            (MergeAlgorithm.SLERP, MergeStrategyParameters(interpolation=0.5)),
            (MergeAlgorithm.TIES, MergeStrategyParameters(density=0.8, merge_coefficient=1.0)),
            (MergeAlgorithm.DARE, MergeStrategyParameters(density=0.8, merge_coefficient=1.0)),
            (MergeAlgorithm.TASK_ARITHMETIC, MergeStrategyParameters(merge_coefficient=0.5)),
        )
        if not grid or len(grid) > self._max_plans:
            raise MergeEvaluationPlanError("strategy grid is empty or exceeds max_plans")
        for algorithm, params in grid:
            if not isinstance(algorithm, MergeAlgorithm):
                raise MergeEvaluationPlanError("unknown merge algorithm")
            _validate_parameters(algorithm, params)

        plans = []
        routes = []
        for candidate_id in sorted(selected):
            item = by_id[candidate_id]
            entry = item.entry
            if entry.enabled or entry.status != "pending_human_approval":
                raise MergeEvaluationPlanError("enabled or non-pending candidate is ineligible")
            if entry.evaluation_suite_digest != expected_suite_digest or entry.fitness.evaluation_suite_digest != expected_suite_digest:
                raise MergeEvaluationPlanError("candidate evidence suite drift")
            if not _valid_digest(entry.artifact_digest) or not _valid_digest(entry.evidence_digest):
                raise MergeEvaluationPlanError("candidate artifact/evidence digest is invalid")
            parents = item.parent_descriptors
            if len(parents) < 2 or len(parents) > 4:
                raise MergeEvaluationPlanError("each candidate requires 2-4 parent descriptors")
            for parent in parents:
                if not isinstance(parent, ModelDescriptor) or not _valid_digest(parent.artifact_digest):
                    raise MergeEvaluationPlanError("parent descriptor or artifact digest is invalid")
                if not _ID.fullmatch(parent.model_id):
                    raise MergeEvaluationPlanError("invalid parent model identity")

            # Stage 141 checks basic metadata. Stage 154 adds explicit quantization,
            # provenance, digest, and local-artifact checks before any parameter strategy.
            compatibility = assess_compatibility(parents)
            reasons = list(compatibility.reasons)
            if len({p.quantization for p in parents}) != 1:
                reasons.append("incompatible quantization")
            if len({p.provenance for p in parents}) != 1:
                reasons.append("provenance mismatch requires independent review")
            if any(not p.local_artifact_available for p in parents):
                reasons.append("non-local parent artifact")
            if not compatibility.compatible or compatibility.strategy is not MergeStrategy.PARAMETER or reasons != list(compatibility.reasons):
                routes.append(OrchestrationRoute(candidate_id, tuple(dict.fromkeys(reasons))))
                continue

            for algorithm, params in grid:
                payload = {
                    "candidate": candidate_id, "generation": entry.generation,
                    "algorithm": algorithm.value,
                    "parameters": {
                        "interpolation": params.interpolation, "density": params.density,
                        "merge_coefficient": params.merge_coefficient,
                        "lora_rank": params.lora_rank, "lora_alpha": params.lora_alpha,
                    },
                    "parents": [(p.model_id, p.artifact_digest) for p in parents],
                    "candidate_artifact": entry.artifact_digest,
                    "suite": expected_suite_digest,
                    "source_selection": selection.digest,
                }
                canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
                recipe = hashlib.sha256(canonical.encode()).hexdigest()
                plans.append(MergeEvaluationPlan(
                    plan_id=hashlib.sha256(("plan:" + recipe).encode()).hexdigest(),
                    candidate_id=candidate_id, generation=entry.generation,
                    algorithm=algorithm, parameters=params,
                    parent_model_ids=tuple(p.model_id for p in parents),
                    parent_artifact_digests=tuple(p.artifact_digest for p in parents),
                    candidate_artifact_digest=entry.artifact_digest,
                    evaluation_suite_digest=expected_suite_digest,
                    recipe_digest=recipe, strategy="parameter_merge",
                ))
                if len(plans) > self._max_plans:
                    raise MergeEvaluationPlanError("expanded plan count exceeds max_plans")

        payload = {
            "suite": expected_suite_digest, "selection": selection.digest,
            "plans": [x.recipe_digest for x in plans],
            "routes": [(x.candidate_id, x.reasons) for x in routes],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return MergeEvaluationPlanReport(
            expected_suite_digest, selection.digest, tuple(plans), tuple(routes), digest,
        )


__all__ = [
    "MergeEvaluationPlanError", "MergeAlgorithm", "MergeStrategyParameters",
    "MergeEvaluationPlan", "OrchestrationRoute", "MergeEvaluationPlanReport",
    "EvolutionaryMergeEvaluationPlanner",
]
