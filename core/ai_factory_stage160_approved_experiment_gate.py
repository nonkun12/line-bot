"""Stage 160: explicit-approval gate for isolated evolutionary experiments.

Execution is possible only when a caller explicitly supplies a one-time human
approval token. This coordinator has no scheduler, token issuer, or runtime adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable

from .ai_factory_stage154_merge_strategy_evaluation import MergeEvaluationPlan
from .ai_factory_stage155_isolated_merge_experiments import (
    IndependentEvaluationEvidence, IndependentEvaluator, IsolatedMergeExperimentRunner,
    IsolatedSandbox, MergeExperimentOutcome, SandboxPolicy,
)
from .ai_factory_stage159_evolutionary_experiment_handoff import ExperimentDispatchProposal

_HEX = re.compile(r"[0-9a-f]{64}")


class ApprovedExperimentGateError(ValueError):
    """Raised when approval, proposal integrity, lineage, or safety gates fail."""


@dataclass(frozen=True)
class ApprovedExperimentExecution:
    proposal_id: str
    proposal_digest: str
    outcome: MergeExperimentOutcome
    execution_requested_by_explicit_call: bool
    approval_verified_by_runner: bool
    proposal_only: bool = True
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


def _digest(value: str) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def _proposal_digest(proposal: ExperimentDispatchProposal) -> str:
    canonical = {
        "candidate": proposal.candidate_id,
        "strategy": proposal.strategy,
        "plan": proposal.plan_id,
        "generation": proposal.generation,
        "recipe": proposal.recipe_digest,
        "candidate_artifact": proposal.candidate_artifact_digest,
        "parents": list(proposal.parent_artifact_digests),
        "suite": proposal.evaluation_suite_digest,
        "tournament": proposal.tournament_digest,
        "score": proposal.strategy_score_digest,
        "approval_scope": proposal.required_approval_scope,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class ApprovedEvolutionaryExperimentGate:
    """Invokes Stage 155 only after an explicit, proposal-bound human approval."""

    def execute(
        self,
        *,
        proposal: ExperimentDispatchProposal,
        plan: MergeEvaluationPlan,
        approval_token: str,
        verify_approval: Callable[[str, str], bool],
        sandbox: IsolatedSandbox,
        evaluator: IndependentEvaluator,
        verify_evaluation_evidence: Callable[[IndependentEvaluationEvidence], bool],
        baseline_fitness,
        runner: IsolatedMergeExperimentRunner | None = None,
        policy: SandboxPolicy = SandboxPolicy(),
        hold_active: bool = False,
        kill_switch_active: bool = False,
        budget_available: bool = True,
    ) -> ApprovedExperimentExecution:
        if hold_active or kill_switch_active or not budget_available:
            raise ApprovedExperimentGateError("HOLD, kill switch, or unavailable budget blocks experiment execution")
        if not isinstance(proposal, ExperimentDispatchProposal) or not isinstance(plan, MergeEvaluationPlan):
            raise ApprovedExperimentGateError("typed Stage 159 proposal and Stage 154 plan are required")
        if (proposal.proposal_only is not True or proposal.approval_required is not True
                or proposal.approval_consumed is not False
                or proposal.execution_authorized is not False
                or proposal.merge_authorized is not False
                or proposal.weight_mutation_authorized is not False
                or proposal.generation_advanced is not False
                or proposal.model_activated is not False):
            raise ApprovedExperimentGateError("proposal is not an unconsumed, non-authoritative approval request")
        if (not _digest(proposal.digest) or proposal.digest != _proposal_digest(proposal)
                or not _digest(proposal.proposal_id)
                or proposal.proposal_id != hashlib.sha256(("stage159:" + proposal.digest).encode()).hexdigest()):
            raise ApprovedExperimentGateError("Stage 159 proposal digest or identity is invalid")
        if proposal.required_approval_scope != "single-plan-recipe-digest":
            raise ApprovedExperimentGateError("approval scope must be limited to one exact recipe digest")
        if (plan.plan_id != proposal.plan_id or plan.candidate_id != proposal.candidate_id
                or plan.generation != proposal.generation or plan.algorithm.value != proposal.strategy
                or plan.recipe_digest != proposal.recipe_digest
                or plan.candidate_artifact_digest != proposal.candidate_artifact_digest
                or plan.parent_artifact_digests != proposal.parent_artifact_digests
                or plan.evaluation_suite_digest != proposal.evaluation_suite_digest):
            raise ApprovedExperimentGateError("execution plan does not match the exact Stage 159 proposal lineage")
        if (plan.execution_authorized is not False or plan.merge_authorized is not False
                or plan.activation_authorized is not False or plan.independent_evaluation_required is not True):
            raise ApprovedExperimentGateError("Stage 154 plan contains forbidden authority or skips independent evaluation")
        if not isinstance(approval_token, str) or not approval_token.strip() or len(approval_token) > 4096:
            raise ApprovedExperimentGateError("explicit one-time human approval token is required")
        if not callable(verify_approval) or not callable(verify_evaluation_evidence):
            raise ApprovedExperimentGateError("independent approval and evaluation verifiers are required")
        active_runner = runner or IsolatedMergeExperimentRunner()
        if not isinstance(active_runner, IsolatedMergeExperimentRunner):
            raise ApprovedExperimentGateError("typed Stage 155 isolated experiment runner is required")

        # Stage 155 verifies/consumes the token through the injected verifier,
        # then delegates to the offline sandbox and distinct independent evaluator.
        outcome = active_runner.run(
            plan=plan,
            approval_token=approval_token,
            verify_approval=verify_approval,
            sandbox=sandbox,
            evaluator=evaluator,
            verify_evaluation_evidence=verify_evaluation_evidence,
            baseline_fitness=baseline_fitness,
            policy=policy,
        )
        if not isinstance(outcome, MergeExperimentOutcome) or outcome.plan_id != plan.plan_id:
            raise ApprovedExperimentGateError("Stage 155 returned an invalid or mismatched experiment outcome")
        return ApprovedExperimentExecution(
            proposal.proposal_id, proposal.digest, outcome, True, True,
        )


__all__ = [
    "ApprovedExperimentGateError", "ApprovedExperimentExecution",
    "ApprovedEvolutionaryExperimentGate",
]
