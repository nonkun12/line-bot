"""Stage 165: authenticated recursive feedback from measured evolutionary trials.

Unlike the success-only knowledge-transfer path, this ledger retains verified
regressions and failed trials as diagnostic evidence. It proposes lessons for the
next generation without selecting, adopting, or activating a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable

from .ai_factory_stage141_evolution import Fitness
from .ai_factory_stage154_merge_strategy_evaluation import MergeEvaluationPlan
from .ai_factory_stage156_authenticated_knowledge_transfer import Stage156SignedEvidence
from .ai_factory_stage160_approved_experiment_gate import ApprovedExperimentExecution
from .ai_factory_stage164_adaptive_experiment_design import AdaptiveExperimentDesignReport, DesignAttestation

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_PARAMETER_BINDINGS = {
    "slerp": (("interpolation_coefficient", "interpolation"),),
    "ties": (("density", "density"),),
    "dare": (("drop_rate", "density"),),
    "task_arithmetic": (("task_vector_scale", "merge_coefficient"),),
    "lora": (("adapter_rank", "lora_rank"),),
}


class RecursiveEvolutionFeedbackError(ValueError):
    """Raised when trial evidence cannot safely enter recursive learning."""


@dataclass(frozen=True)
class RecursiveTrialRecord:
    outcome_digest: str
    evidence_digest: str
    design_digest: str
    plan_id: str
    recipe_digest: str
    strategy: str
    source_generation: int
    proposed_generation: int
    classification: str
    metrics: tuple[tuple[str, float], ...]
    baseline_metrics: tuple[tuple[str, float], ...]
    lessons: tuple[str, ...]
    record_digest: str
    pending_human_approval: bool = True
    generation_advanced: bool = False
    model_activated: bool = False
    model_mutation_authorized: bool = False
    production_switch_authorized: bool = False


@dataclass(frozen=True)
class StrategyEvolutionSummary:
    strategy: str
    observations: int
    improved: int
    regressed: int
    safety_failures: int
    stagnant: int
    repeatability_required: int
    next_generation_guidance: tuple[str, ...]


@dataclass(frozen=True)
class RecursiveEvolutionFeedbackSnapshot:
    records: tuple[RecursiveTrialRecord, ...]
    summaries: tuple[StrategyEvolutionSummary, ...]
    evaluation_suite_digest: str
    digest: str
    proposal_only: bool = True
    generation_advanced: bool = False
    model_activated: bool = False
    model_mutation_authorized: bool = False
    production_switch_authorized: bool = False


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _fitness_metrics(value: Fitness, suite: str) -> dict[str, float]:
    if not isinstance(value, Fitness) or value.evaluation_suite_digest != suite:
        raise RecursiveEvolutionFeedbackError("fitness must be bound to the exact frozen evaluation suite")
    metrics = {
        "accuracy": value.accuracy,
        "instruction_following": value.instruction_following,
        "safety": value.safety,
        "latency_ms": value.latency_ms,
        "memory_mb": value.memory_mb,
        "regression_count": value.regression_count,
    }
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in metrics.values()):
        raise RecursiveEvolutionFeedbackError("fitness metrics must be finite numeric values")
    if not 0 <= value.accuracy <= 1 or not 0 <= value.instruction_following <= 1 or not 0 <= value.safety <= 1:
        raise RecursiveEvolutionFeedbackError("normalized fitness metrics must be within [0, 1]")
    if value.latency_ms <= 0 or value.memory_mb <= 0 or value.regression_count < 0:
        raise RecursiveEvolutionFeedbackError("resource metrics and regression count are invalid")
    return metrics


def _recipe_for(report: AdaptiveExperimentDesignReport, strategy: str):
    matches = [x for x in report.recipes if x.strategy == strategy]
    if len(matches) != 1:
        raise RecursiveEvolutionFeedbackError("exactly one Stage 164 recipe must match the executed strategy")
    return matches[0]


def _validate_recipe_parameters(plan: MergeEvaluationPlan, recipe) -> None:
    bindings = _PARAMETER_BINDINGS.get(recipe.strategy)
    if bindings is None:
        if recipe.strategy == "multi_model_orchestration":
            raise RecursiveEvolutionFeedbackError("orchestration route cannot be executed as a parameter-merge plan")
        if recipe.strategy == "parameter_merge":
            raise RecursiveEvolutionFeedbackError("generic parameter_merge is not an executable merge algorithm")
        raise RecursiveEvolutionFeedbackError("unsupported strategy recipe")
    if plan.algorithm.value != recipe.strategy:
        raise RecursiveEvolutionFeedbackError("Stage 154 algorithm does not match the Stage 164 recipe")
    for axis_name, field_name in bindings:
        axes = [axis for axis in recipe.search_axes if axis[0] == axis_name]
        if len(axes) != 1:
            raise RecursiveEvolutionFeedbackError("recipe is missing the strategy-specific bounded search axis")
        _, low, high = axes[0]
        value = getattr(plan.parameters, field_name)
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or not low <= value <= high):
            raise RecursiveEvolutionFeedbackError("executed parameter falls outside the Stage 164 search envelope")


class RecursiveEvolutionFeedbackIntegrator:
    """Append-only verified trial ledger, retaining both wins and failures."""

    def __init__(self, *, max_records: int = 512) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= 4096:
            raise ValueError("max_records must be between 1 and 4096")
        self._max_records = max_records
        self._records: list[RecursiveTrialRecord] = []
        self._outcomes: set[str] = set()
        self._suite_by_generation: dict[int, str] = {}

    def ingest(
        self,
        *,
        design: AdaptiveExperimentDesignReport,
        design_attestation: DesignAttestation,
        execution: ApprovedExperimentExecution,
        plan: MergeEvaluationPlan,
        evidence: Stage156SignedEvidence,
        baseline_fitness: Fitness,
        verify_design_attestation: Callable[[AdaptiveExperimentDesignReport, DesignAttestation], bool],
        verify_trial_evidence: Callable[[Stage156SignedEvidence], bool],
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> RecursiveTrialRecord:
        if hold_active or kill_switch_active or not budget_available:
            raise RecursiveEvolutionFeedbackError("HOLD, kill switch, or unavailable budget blocks feedback ingestion")
        if not isinstance(design, AdaptiveExperimentDesignReport) or not isinstance(design_attestation, DesignAttestation):
            raise RecursiveEvolutionFeedbackError("typed Stage 164 design and attestation are required")
        if not isinstance(execution, ApprovedExperimentExecution) or not isinstance(plan, MergeEvaluationPlan):
            raise RecursiveEvolutionFeedbackError("typed Stage 160 approved execution and Stage 154 plan are required")
        if not isinstance(evidence, Stage156SignedEvidence):
            raise RecursiveEvolutionFeedbackError("typed independent signed evaluation evidence is required")
        if (design.proposal_only is not True or design.experiment_execution_authorized
                or design.model_selection_authorized or design.model_mutation_authorized
                or design.generation_advanced or design.model_activated
                or design.production_switch_authorized):
            raise RecursiveEvolutionFeedbackError("Stage 164 design carries forbidden authority")
        if (execution.execution_requested_by_explicit_call is not True
                or execution.approval_verified_by_runner is not True
                or execution.proposal_only is not True
                or execution.generation_advanced is not False
                or execution.model_activated is not False
                or execution.production_switch_authorized is not False):
            raise RecursiveEvolutionFeedbackError("execution lacks explicit one-time human approval or safe authority state")
        if (plan.execution_authorized is not False or plan.merge_authorized is not False
                or plan.activation_authorized is not False or plan.independent_evaluation_required is not True):
            raise RecursiveEvolutionFeedbackError("Stage 154 plan contains forbidden authority")
        if (not _valid_digest(design.design_digest) or not _valid_digest(design.evaluation_suite_digest)
                or not _valid_digest(design_attestation.design_digest)
                or design_attestation.design_digest != design.design_digest
                or design_attestation.evaluation_suite_digest != design.evaluation_suite_digest
                or design_attestation.source_generation != design.source_generation
                or not _ID.fullmatch(design_attestation.evaluator_id or "")
                or not isinstance(design_attestation.signature, str) or not design_attestation.signature.strip()
                or len(design_attestation.signature) > 8192):
            raise RecursiveEvolutionFeedbackError("design attestation or frozen-suite binding is invalid")
        if not callable(verify_design_attestation) or not verify_design_attestation(design, design_attestation):
            raise RecursiveEvolutionFeedbackError("independent Stage 164 design attestation verification failed")
        if plan.generation != design.source_generation or plan.evaluation_suite_digest != design.evaluation_suite_digest:
            raise RecursiveEvolutionFeedbackError("plan generation or evaluation suite drifted from Stage 164 design")
        recipe = _recipe_for(design, plan.algorithm.value)
        _validate_recipe_parameters(plan, recipe)
        if (not _valid_digest(plan.recipe_digest) or not _valid_digest(plan.candidate_artifact_digest)
                or not all(_valid_digest(x) for x in plan.parent_artifact_digests)
                or not _ID.fullmatch(plan.plan_id or "") or not _ID.fullmatch(plan.candidate_id or "")):
            raise RecursiveEvolutionFeedbackError("Stage 154 plan identity or artifact lineage is invalid")
        outcome = execution.outcome
        if (outcome.plan_id != plan.plan_id or outcome.recipe_digest != plan.recipe_digest
                or outcome.generation_advanced is not False or outcome.model_activated is not False
                or outcome.production_switch_authorized is not False
                or not _valid_digest(outcome.outcome_digest)
                or not _valid_digest(outcome.output_artifact_digest)
                or not _valid_digest(outcome.evaluation_evidence_digest)
                or outcome.evaluator_id != evidence.evaluator_id
                or outcome.output_artifact_digest != evidence.artifact_digest
                or outcome.evaluation_evidence_digest != evidence.evidence_digest
                or outcome.outcome_digest != evidence.outcome_digest):
            raise RecursiveEvolutionFeedbackError("Stage 155 outcome does not bind to exact plan and signed evidence")
        if (evidence.source_generation != plan.generation
                or evidence.evaluation_suite_digest != design.evaluation_suite_digest
                or evidence.parent_model_ids != plan.parent_model_ids
                or evidence.parent_artifact_digests != plan.parent_artifact_digests
                or not _ID.fullmatch(evidence.evaluator_id or "")
                or not isinstance(evidence.signature, str) or not evidence.signature.strip()
                or len(evidence.signature) > 8192):
            raise RecursiveEvolutionFeedbackError("independent evidence lineage or signature metadata is invalid")
        if not callable(verify_trial_evidence) or not verify_trial_evidence(evidence):
            raise RecursiveEvolutionFeedbackError("independent trial evidence verification failed")
        if outcome.outcome_digest in self._outcomes:
            raise RecursiveEvolutionFeedbackError("duplicate or replayed trial outcome")
        if len(self._records) >= self._max_records:
            raise RecursiveEvolutionFeedbackError("recursive feedback ledger capacity reached")
        if self._records and plan.generation < max(x.source_generation for x in self._records):
            raise RecursiveEvolutionFeedbackError("out-of-order generation feedback is rejected")
        if plan.generation in self._suite_by_generation and self._suite_by_generation[plan.generation] != design.evaluation_suite_digest:
            raise RecursiveEvolutionFeedbackError("evaluation suite drift within a generation")

        measured = _fitness_metrics(evidence.fitness, design.evaluation_suite_digest)
        baseline = _fitness_metrics(baseline_fitness, design.evaluation_suite_digest)
        safety_failure = measured["safety"] < 0.95 or measured["safety"] < baseline["safety"]
        regression = (
            measured["accuracy"] < baseline["accuracy"]
            or measured["instruction_following"] < baseline["instruction_following"]
            or measured["latency_ms"] > baseline["latency_ms"] * 1.10
            or measured["memory_mb"] > baseline["memory_mb"] * 1.10
            or measured["regression_count"] > 0
        )
        improved = (
            measured["accuracy"] > baseline["accuracy"]
            or measured["instruction_following"] > baseline["instruction_following"]
            or measured["safety"] > baseline["safety"]
            or measured["latency_ms"] < baseline["latency_ms"]
            or measured["memory_mb"] < baseline["memory_mb"]
        )
        expected_acceptance = not safety_failure and not regression and improved
        if outcome.accepted_for_next_generation is not expected_acceptance:
            raise RecursiveEvolutionFeedbackError("Stage 155 acceptance flag conflicts with independently measured metrics")
        if safety_failure:
            classification = "SAFETY_FAILURE"
        elif regression:
            classification = "REGRESSED"
        elif improved:
            classification = "IMPROVED"
        else:
            classification = "STAGNANT"

        lessons = []
        if safety_failure:
            lessons.append("exclude strategy from candidate retention; isolate safety failure before retry")
        if regression:
            lessons.append("record regression dimensions and narrow the next diagnostic search")
        if not improved:
            lessons.append("do not promote; diversify parameters or strategy before another trial")
        if classification == "IMPROVED":
            lessons.append("retain as a measured candidate proposal; require independent repeatability before selection")
        lessons.append("carry this verified observation into the next generation policy without automatic adoption")

        metrics_tuple = tuple(sorted((k, float(v)) for k, v in measured.items()))
        baseline_tuple = tuple(sorted((k, float(v)) for k, v in baseline.items()))
        canonical = {
            "outcome": outcome.outcome_digest, "evidence": evidence.evidence_digest,
            "design": design.design_digest, "plan": plan.plan_id,
            "recipe": plan.recipe_digest, "strategy": recipe.strategy,
            "generation": plan.generation, "classification": classification,
            "metrics": metrics_tuple, "baseline": baseline_tuple, "lessons": lessons,
        }
        digest = hashlib.sha256(json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        record = RecursiveTrialRecord(
            outcome.outcome_digest, evidence.evidence_digest, design.design_digest,
            plan.plan_id, plan.recipe_digest, recipe.strategy, plan.generation,
            plan.generation + 1, classification, metrics_tuple, baseline_tuple,
            tuple(lessons), digest,
        )
        self._records.append(record)
        self._outcomes.add(outcome.outcome_digest)
        self._suite_by_generation[plan.generation] = design.evaluation_suite_digest
        return record

    def snapshot(self) -> RecursiveEvolutionFeedbackSnapshot:
        grouped: dict[str, list[RecursiveTrialRecord]] = {}
        for record in self._records:
            grouped.setdefault(record.strategy, []).append(record)
        summaries = []
        for strategy, records in sorted(grouped.items()):
            improved = sum(x.classification == "IMPROVED" for x in records)
            regressed = sum(x.classification == "REGRESSED" for x in records)
            safety = sum(x.classification == "SAFETY_FAILURE" for x in records)
            stagnant = sum(x.classification == "STAGNANT" for x in records)
            guidance = []
            if safety:
                guidance.append("safety failure observed: keep candidate retention disabled pending a fresh safety pass")
            if regressed:
                guidance.append("regression observed: prioritize the failing metric and run independent repeats")
            if stagnant:
                guidance.append("stagnation observed: allocate bounded diversity to alternative strategies or parameter regions")
            if improved:
                guidance.append("improvement observed: request repeatability evidence; do not auto-select")
            summaries.append(StrategyEvolutionSummary(
                strategy, len(records), improved, regressed, safety, stagnant,
                max(0, len(records) * 2 - improved),
                tuple(guidance or ("collect more independently evaluated trials",)),
            ))
        suites = sorted(set(self._suite_by_generation.values()))
        suite = suites[-1] if suites else ""
        payload = {
            "records": [x.record_digest for x in self._records],
            "summaries": [{
                "strategy": x.strategy, "observations": x.observations,
                "improved": x.improved, "regressed": x.regressed,
                "safety_failures": x.safety_failures, "stagnant": x.stagnant,
                "repeatability_required": x.repeatability_required,
                "guidance": list(x.next_generation_guidance),
            } for x in summaries],
            "suite": suite,
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return RecursiveEvolutionFeedbackSnapshot(
            tuple(self._records), tuple(summaries), suite, digest,
        )


__all__ = [
    "RecursiveEvolutionFeedbackError", "RecursiveTrialRecord",
    "StrategyEvolutionSummary", "RecursiveEvolutionFeedbackSnapshot",
    "RecursiveEvolutionFeedbackIntegrator",
]
