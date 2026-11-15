"""Stage 164: adaptive experiment design for recursive evolutionary model merging.

Combines Stage 163 failure profiles with Stage 162 bounded strategy priors to
produce deterministic, frozen-suite experiment proposals. It does not execute
experiments, mutate weights, select models, or advance generations.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable

from .ai_factory_stage162_evolutionary_policy_learning import EvolutionarySelectionPolicy
from .ai_factory_stage163_failure_informed_exploration import AdaptiveExplorationPlan

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

# Bounds are proposal envelopes, not instructions to execute or merge weights.
_STRATEGY_AXES = {
    "slerp": (("interpolation_coefficient", 0.20, 0.80),),
    "ties": (("density", 0.20, 0.80),),
    "dare": (("drop_rate", 0.05, 0.50),),
    "task_arithmetic": (("task_vector_scale", 0.10, 1.50),),
    "lora": (("adapter_rank", 4.0, 16.0),),
    "parameter_merge": (),
    "multi_model_orchestration": (),
}


class AdaptiveExperimentDesignError(ValueError):
    """Raised when adaptive experiment inputs are incomplete or unsafe."""


@dataclass(frozen=True)
class DesignAttestation:
    source_plan_digest: str
    evaluation_suite_digest: str
    source_generation: int
    evaluator_id: str
    signature: str


@dataclass(frozen=True)
class AdaptiveExperimentRecipe:
    strategy: str
    diagnostic_focus: tuple[str, ...]
    evaluation_dimensions: tuple[str, ...]
    search_axes: tuple[tuple[str, float, float], ...]
    repeat_count: int
    exploration_share: float
    historical_prior: float
    candidate_retention_eligible: bool
    execution_authorized: bool = False
    weight_mutation_authorized: bool = False


@dataclass(frozen=True)
class AdaptiveExperimentDesignReport:
    source_exploration_digest: str
    policy_digest: str
    evaluation_suite_digest: str
    source_generation: int
    recipes: tuple[AdaptiveExperimentRecipe, ...]
    total_repeat_budget: int
    design_digest: str
    proposal_only: bool = True
    experiment_execution_authorized: bool = False
    model_selection_authorized: bool = False
    model_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


class AdaptiveExperimentDesigner:
    """Turns verified failure profiles into bounded next-trial design proposals."""

    def design(
        self,
        exploration: AdaptiveExplorationPlan,
        attestation: DesignAttestation,
        policy: EvolutionarySelectionPolicy,
        *,
        verify_attestation: Callable[[AdaptiveExplorationPlan, DesignAttestation], bool],
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
        max_recipes: int = 16,
        max_total_repeats: int = 64,
    ) -> AdaptiveExperimentDesignReport:
        if hold_active or kill_switch_active or not budget_available:
            raise AdaptiveExperimentDesignError("HOLD, kill switch, or unavailable budget blocks experiment design")
        if not isinstance(exploration, AdaptiveExplorationPlan) or not isinstance(policy, EvolutionarySelectionPolicy):
            raise AdaptiveExperimentDesignError("typed Stage 163 exploration and Stage 162 policy are required")
        if not isinstance(attestation, DesignAttestation) or not callable(verify_attestation):
            raise AdaptiveExperimentDesignError("independent Stage 163 plan attestation and verifier are required")
        if (not exploration.proposal_only or exploration.experiment_execution_authorized
                or exploration.selection_authorized or exploration.model_mutation_authorized
                or exploration.generation_advanced or exploration.model_activated
                or exploration.production_switch_authorized):
            raise AdaptiveExperimentDesignError("Stage 163 plan contains forbidden authority")
        if (not policy.proposal_only or policy.selection_authorized or policy.execution_authorized
                or policy.model_mutation_authorized or policy.model_activated):
            raise AdaptiveExperimentDesignError("Stage 162 policy contains forbidden authority")
        if (not _HEX.fullmatch(exploration.plan_digest or "")
                or not _HEX.fullmatch(exploration.evaluation_suite_digest or "")
                or not _HEX.fullmatch(policy.policy_digest or "")
                or attestation.source_plan_digest != exploration.plan_digest
                or attestation.evaluation_suite_digest != exploration.evaluation_suite_digest
                or policy.evaluation_suite_digest != exploration.evaluation_suite_digest
                or not _HEX.fullmatch(attestation.source_plan_digest or "")
                or not _HEX.fullmatch(attestation.evaluation_suite_digest or "")
                or attestation.source_generation != exploration.source_generation
                or not isinstance(attestation.source_generation, int)
                or isinstance(attestation.source_generation, bool)
                or attestation.source_generation < 0
                or not _ID.fullmatch(attestation.evaluator_id or "")
                or not isinstance(attestation.signature, str)
                or not attestation.signature.strip() or len(attestation.signature) > 8192):
            raise AdaptiveExperimentDesignError("attestation, generation, or frozen-suite binding is invalid")
        if not verify_attestation(exploration, attestation):
            raise AdaptiveExperimentDesignError("independent Stage 163 plan attestation verification failed")
        if not isinstance(max_recipes, int) or isinstance(max_recipes, bool) or not 1 <= max_recipes <= 32:
            raise AdaptiveExperimentDesignError("max_recipes must be between 1 and 32")
        if not isinstance(max_total_repeats, int) or isinstance(max_total_repeats, bool) or not 1 <= max_total_repeats <= 128:
            raise AdaptiveExperimentDesignError("max_total_repeats must be between 1 and 128")
        if not exploration.profiles or len(exploration.profiles) > max_recipes:
            raise AdaptiveExperimentDesignError("Stage 163 profile set is empty or exceeds recipe capacity")

        priors = {}
        for item in policy.learnings:
            if item.strategy in priors:
                raise AdaptiveExperimentDesignError("duplicate learned strategy prior")
            if (not isinstance(item.prior_score, (int, float)) or isinstance(item.prior_score, bool)
                    or not math.isfinite(item.prior_score)
                    or abs(item.prior_score) > policy.max_prior_influence):
                raise AdaptiveExperimentDesignError("learned strategy prior exceeds its bounded influence")
            priors[item.strategy] = float(item.prior_score)

        recipes = []
        seen = set()
        for profile in exploration.profiles:
            strategy = profile.strategy
            if strategy in seen or strategy not in _STRATEGY_AXES:
                raise AdaptiveExperimentDesignError("duplicate or unsupported strategy in failure profile")
            seen.add(strategy)
            if (not isinstance(profile.recommended_repeats, int)
                    or isinstance(profile.recommended_repeats, bool)
                    or not 2 <= profile.recommended_repeats <= 4
                    or not isinstance(profile.exploration_share, (int, float))
                    or isinstance(profile.exploration_share, bool)
                    or not math.isfinite(profile.exploration_share)
                    or not 0 < profile.exploration_share <= 1):
                raise AdaptiveExperimentDesignError("failure profile repeats or exploration share is invalid")
            failures = (
                profile.repeatability_failures, profile.safety_failures,
                profile.regression_failures, profile.evidence_shortfalls,
            )
            if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in failures):
                raise AdaptiveExperimentDesignError("failure counters must be non-negative integers")

            focus = []
            if profile.safety_failures:
                focus.append("safety")
            if profile.regression_failures:
                focus.append("regression_localization")
            if profile.repeatability_failures:
                focus.append("repeatability_variance")
            if profile.evidence_shortfalls:
                focus.append("evidence_completeness")
            if not focus:
                focus.append("balanced_quality_and_resource_validation")
            dimensions = ["accuracy", "instruction_following", "safety", "latency_ms", "memory_mb"]
            # Keep the complete frozen evaluation suite; focus changes analysis priority only.
            recipes.append(AdaptiveExperimentRecipe(
                strategy=strategy,
                diagnostic_focus=tuple(focus),
                evaluation_dimensions=tuple(dimensions),
                search_axes=_STRATEGY_AXES[strategy],
                repeat_count=profile.recommended_repeats,
                exploration_share=float(profile.exploration_share),
                historical_prior=priors.get(strategy, 0.0),
                candidate_retention_eligible=bool(profile.retain_as_candidate),
            ))

        total_repeats = sum(x.repeat_count for x in recipes)
        if total_repeats > max_total_repeats:
            raise AdaptiveExperimentDesignError("total repeat budget exceeds configured capacity")
        share_total = sum(x.exploration_share for x in recipes)
        if share_total > 1.000000001:
            raise AdaptiveExperimentDesignError("exploration shares exceed the global allocation")

        payload = {
            "source": exploration.plan_digest,
            "policy": policy.policy_digest,
            "suite": exploration.evaluation_suite_digest,
            "generation": exploration.source_generation,
            "recipes": [{
                "strategy": x.strategy, "focus": list(x.diagnostic_focus),
                "dimensions": list(x.evaluation_dimensions),
                "axes": [list(axis) for axis in x.search_axes],
                "repeats": x.repeat_count, "share": x.exploration_share,
                "prior": x.historical_prior, "retain": x.candidate_retention_eligible,
            } for x in recipes],
            "total_repeats": total_repeats,
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        return AdaptiveExperimentDesignReport(
            exploration.plan_digest, policy.policy_digest,
            exploration.evaluation_suite_digest, exploration.source_generation,
            tuple(recipes), total_repeats, digest,
        )


__all__ = [
    "AdaptiveExperimentDesignError", "DesignAttestation",
    "AdaptiveExperimentRecipe", "AdaptiveExperimentDesignReport",
    "AdaptiveExperimentDesigner",
]
