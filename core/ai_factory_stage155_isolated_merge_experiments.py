"""Stage 155: approval-gated isolated merge experiments and independent evaluation.

The module contains no shell/process/network implementation. It delegates execution to
an injected sandbox adapter whose receipt is checked before independent evaluation.
A successful result is only a proposal for the next generation, never an activation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable, Protocol

from .ai_factory_stage141_evolution import Fitness
from .ai_factory_stage154_merge_strategy_evaluation import MergeEvaluationPlan

_HEX = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class IsolatedMergeExperimentError(ValueError):
    """Raised when approval, sandbox, or independent-evaluation evidence is unsafe."""


@dataclass(frozen=True)
class SandboxPolicy:
    network_enabled: bool = False
    parent_artifacts_read_only: bool = True
    output_directory_isolated: bool = True
    secrets_allowed: bool = False
    max_runtime_seconds: int = 900
    max_memory_mb: int = 8192
    max_cpu_cores: int = 4
    max_output_mb: int = 4096

    def __post_init__(self) -> None:
        if self.network_enabled or not self.parent_artifacts_read_only or not self.output_directory_isolated or self.secrets_allowed:
            raise ValueError("sandbox must be offline, read-only for inputs, isolated for outputs, and secret-free")
        for name, low, high in (
            ("max_runtime_seconds", 1, 3600), ("max_memory_mb", 256, 65536),
            ("max_cpu_cores", 1, 16), ("max_output_mb", 64, 32768),
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f"{name} is outside its safe bound")


@dataclass(frozen=True)
class SandboxExecutionReceipt:
    plan_id: str
    recipe_digest: str
    output_artifact_digest: str
    sandbox_id: str
    executor_id: str
    exit_code: int
    network_was_disabled: bool
    parent_inputs_were_read_only: bool
    output_was_isolated: bool
    resource_limits_were_enforced: bool
    secrets_were_exposed: bool = False


@dataclass(frozen=True)
class IndependentEvaluationEvidence:
    evaluator_id: str
    artifact_digest: str
    evaluation_suite_digest: str
    fitness: Fitness
    evidence_digest: str
    signature: str


@dataclass(frozen=True)
class MergeExperimentOutcome:
    plan_id: str
    recipe_digest: str
    output_artifact_digest: str
    evaluation_evidence_digest: str
    evaluator_id: str
    accepted_for_next_generation: bool
    reasons: tuple[str, ...]
    outcome_digest: str
    proposal_only: bool = True
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


class IsolatedSandbox(Protocol):
    def execute(self, *, plan: MergeEvaluationPlan, policy: SandboxPolicy) -> SandboxExecutionReceipt: ...


class IndependentEvaluator(Protocol):
    def evaluate(self, *, artifact_digest: str, evaluation_suite_digest: str) -> IndependentEvaluationEvidence: ...


def _digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _validate_fitness(value: Fitness, suite: str) -> None:
    if not isinstance(value, Fitness) or value.evaluation_suite_digest != suite:
        raise IsolatedMergeExperimentError("fitness is not bound to the frozen evaluation suite")


class IsolatedMergeExperimentRunner:
    """Runs one approved plan through injected sandbox and independent evaluator adapters."""

    def run(
        self,
        *,
        plan: MergeEvaluationPlan,
        approval_token: str,
        verify_approval: Callable[[str, str], bool],
        sandbox: IsolatedSandbox,
        evaluator: IndependentEvaluator,
        verify_evaluation_evidence: Callable[[IndependentEvaluationEvidence], bool],
        baseline_fitness: Fitness,
        policy: SandboxPolicy = SandboxPolicy(),
    ) -> MergeExperimentOutcome:
        if not isinstance(plan, MergeEvaluationPlan):
            raise IsolatedMergeExperimentError("typed Stage 154 plan is required")
        # Approval is a separate, short-lived human authorization; a plan cannot
        # self-authorize and its immutable authority flags must remain false.
        if (plan.independent_evaluation_required is not True
                or plan.execution_authorized is not False
                or plan.merge_authorized is not False
                or plan.activation_authorized is not False):
            raise IsolatedMergeExperimentError("plan must require independent evaluation and keep all authority flags false")
        if not _digest(plan.recipe_digest) or not _digest(plan.evaluation_suite_digest):
            raise IsolatedMergeExperimentError("plan recipe or suite digest is invalid")
        if not _digest(plan.candidate_artifact_digest) or not plan.parent_artifact_digests:
            raise IsolatedMergeExperimentError("candidate and parent artifact digests are required")
        if any(not _digest(x) for x in plan.parent_artifact_digests):
            raise IsolatedMergeExperimentError("parent artifact digest is invalid")
        if not isinstance(approval_token, str) or not approval_token.strip() or len(approval_token) > 4096:
            raise IsolatedMergeExperimentError("a valid one-time human approval token is required")
        if not callable(verify_approval) or not verify_approval(approval_token, plan.recipe_digest):
            raise IsolatedMergeExperimentError("human approval could not be independently verified")
        _validate_fitness(baseline_fitness, plan.evaluation_suite_digest)
        if not isinstance(policy, SandboxPolicy):
            raise IsolatedMergeExperimentError("validated sandbox policy is required")
        if not callable(getattr(sandbox, "execute", None)) or not callable(getattr(evaluator, "evaluate", None)):
            raise IsolatedMergeExperimentError("sandbox and independent evaluator adapters are required")

        receipt = sandbox.execute(plan=plan, policy=policy)
        if not isinstance(receipt, SandboxExecutionReceipt):
            raise IsolatedMergeExperimentError("sandbox returned an untyped execution receipt")
        if (receipt.plan_id != plan.plan_id or receipt.recipe_digest != plan.recipe_digest
                or not _digest(receipt.output_artifact_digest)
                or receipt.output_artifact_digest in plan.parent_artifact_digests
                or not _ID.fullmatch(receipt.sandbox_id or "")
                or not _ID.fullmatch(receipt.executor_id or "")):
            raise IsolatedMergeExperimentError("sandbox receipt identity or output digest mismatch")
        if receipt.exit_code != 0:
            raise IsolatedMergeExperimentError("sandbox experiment failed")
        if not (receipt.network_was_disabled and receipt.parent_inputs_were_read_only
                and receipt.output_was_isolated and receipt.resource_limits_were_enforced
                and not receipt.secrets_were_exposed):
            raise IsolatedMergeExperimentError("sandbox isolation guarantees were not met")

        evidence = evaluator.evaluate(
            artifact_digest=receipt.output_artifact_digest,
            evaluation_suite_digest=plan.evaluation_suite_digest,
        )
        if not isinstance(evidence, IndependentEvaluationEvidence):
            raise IsolatedMergeExperimentError("independent evaluator returned untyped evidence")
        if (not _ID.fullmatch(evidence.evaluator_id or "")
                or evidence.evaluator_id == receipt.executor_id
                or evidence.artifact_digest != receipt.output_artifact_digest
                or evidence.evaluation_suite_digest != plan.evaluation_suite_digest
                or not _digest(evidence.evidence_digest)
                or not isinstance(evidence.signature, str) or not evidence.signature):
            raise IsolatedMergeExperimentError("independent evaluation identity or evidence binding failed")
        _validate_fitness(evidence.fitness, plan.evaluation_suite_digest)
        if not callable(verify_evaluation_evidence) or not verify_evaluation_evidence(evidence):
            raise IsolatedMergeExperimentError("evaluation signature/evidence verification failed")

        measured = evidence.fitness
        reasons = []
        if measured.safety < 0.95 or measured.safety < baseline_fitness.safety:
            reasons.append("safety regression or safety floor violation")
        if measured.accuracy < baseline_fitness.accuracy:
            reasons.append("accuracy regression")
        if measured.instruction_following < baseline_fitness.instruction_following:
            reasons.append("instruction-following regression")
        if measured.latency_ms > baseline_fitness.latency_ms * 1.10:
            reasons.append("latency regression exceeds 10% tolerance")
        if measured.memory_mb > baseline_fitness.memory_mb * 1.10:
            reasons.append("memory regression exceeds 10% tolerance")
        if measured.regression_count != 0:
            reasons.append("evaluation suite reported regressions")

        improved = (
            measured.accuracy > baseline_fitness.accuracy
            or measured.instruction_following > baseline_fitness.instruction_following
            or measured.safety > baseline_fitness.safety
            or measured.latency_ms < baseline_fitness.latency_ms
            or measured.memory_mb < baseline_fitness.memory_mb
        )
        if not improved:
            reasons.append("no measurable Pareto improvement over baseline")
        accepted = not reasons
        canonical = {
            "plan": plan.plan_id, "recipe": plan.recipe_digest,
            "artifact": receipt.output_artifact_digest, "evidence": evidence.evidence_digest,
            "evaluator": evidence.evaluator_id, "accepted": accepted,
            "reasons": reasons,
        }
        outcome_digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return MergeExperimentOutcome(
            plan.plan_id, plan.recipe_digest, receipt.output_artifact_digest,
            evidence.evidence_digest, evidence.evaluator_id, accepted,
            tuple(reasons), outcome_digest,
        )


__all__ = [
    "IsolatedMergeExperimentError", "SandboxPolicy", "SandboxExecutionReceipt",
    "IndependentEvaluationEvidence", "MergeExperimentOutcome",
    "IsolatedSandbox", "IndependentEvaluator", "IsolatedMergeExperimentRunner",
]
