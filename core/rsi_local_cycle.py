"""End-to-end, approval-gated local RSI cycle.

The runner performs bounded local inference; a distinct evaluator recomputes the
result from immutable benchmark evidence; RSIExecutor verifies and records the
signed evaluation before any observation is promoted into the RSI loop.
"""
from __future__ import annotations

from typing import Callable, Any

from .rsi_executor import (
    ExperimentPlan,
    ExperimentResult,
    IndependentEvaluation,
    Observation,
    RSIExecutor,
    RSIError,
)

_FORBIDDEN_AUTHORITY = {
    "execution_authorized": False,
    "patch_authorized": False,
    "hold_clear_authorized": False,
    "stop_clear_authorized": False,
    "merge_deploy_authorized": False,
    "required_human_approval": True,
}


def run_local_rsi_cycle(
    *,
    plan: ExperimentPlan,
    approval: Any,
    runner: Any,
    evaluator: Any,
    executor: RSIExecutor,
    sign_observation_digest: Callable[[str], str],
    created_at: int,
) -> dict[str, Any]:
    """Run one locally bounded RSI experiment and feed its signed evaluation back.

    Execution is delegated to RSIExecutor.execute_approved, which enforces the
    one-time human approval, FREE-only local runner, budget, and control gates.
    The independent evaluator's deterministic decision is separately verified
    and persisted by RSIExecutor.evaluate before it can become an observation.

    The observation attestation signer must be trusted by the executor's
    verify_evidence_signature callback under evaluator.evaluator_id.
    """
    if not isinstance(plan, ExperimentPlan):
        raise RSIError("typed experiment plan is required")
    if not isinstance(executor, RSIExecutor):
        raise RSIError("RSIExecutor is required")
    if not callable(getattr(evaluator, "evaluate", None)):
        raise RSIError("independent evaluator is required")
    evaluator_id = getattr(evaluator, "evaluator_id", None)
    if not isinstance(evaluator_id, str) or not evaluator_id.strip():
        raise RSIError("independent evaluator identity is missing")
    if not callable(sign_observation_digest):
        raise RSIError("trusted observation attestation signer is required")
    if type(created_at) is not int or created_at < 0:
        raise RSIError("created_at_invalid")

    # Human approval and the FREE/local-only execution policy are enforced here.
    result = executor.execute_approved(plan, approval, runner)
    if not isinstance(result, ExperimentResult):
        raise RSIError("local runner returned an invalid result")

    # The evaluator reads the immutable runner evidence and recomputes metrics.
    evaluation = evaluator.evaluate(plan, result)
    if not isinstance(evaluation, IndependentEvaluation):
        raise RSIError("independent evaluator returned an invalid evaluation")
    # Never let a caller-controlled evaluator object attest under a different
    # identity than the identity embedded in its signed evaluation.
    if evaluation.evaluator_id != evaluator_id:
        raise RSIError("independent evaluator identity does not match its evaluation")
    executor.evaluate(result, evaluation)

    decision_to_outcome = {
        "IMPROVED": "PASS",
        "REGRESSED": "REGRESSED",
        "NO_CHANGE": "INCONCLUSIVE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    }
    outcome = decision_to_outcome.get(evaluation.decision)
    if outcome is None:
        raise RSIError("unsupported independent evaluation decision")

    observation_id = "rsi-local-" + plan.experiment_id
    source_event_id = "rsi-local-source-" + plan.experiment_id
    observation = Observation(
        observation_id=observation_id,
        evidence_digest="0" * 64,
        capability=plan.capability,
        outcome=outcome,
        detail=evaluation.rationale[:2000],
        created_at=created_at,
        evidence_event_id=source_event_id,
        experiment_id=plan.experiment_id,
        candidate_digest=plan.candidate_digest,
        protocol_digest=plan.protocol_digest,
        result_digest=result.result_digest,
    )

    # Fail closed before writing observation evidence if the control gate is shut.
    # The signed independent evaluation remains in the ledger as audit evidence.
    executor._control()
    source_digest = executor.ledger.append_observation_evidence(
        source_event_id,
        observation=observation,
        experiment_id=plan.experiment_id,
        candidate_digest=plan.candidate_digest,
        protocol_digest=plan.protocol_digest,
        result_digest=result.result_digest,
        producer_id=evaluator_id,
        sign_digest=sign_observation_digest,
    )
    from dataclasses import replace

    verified_observation = replace(observation, evidence_digest=source_digest)
    diagnoses = executor.observe((verified_observation,))
    hypotheses = executor.hypothesize(diagnoses) if diagnoses else ()
    plans = executor.plan(
        hypotheses,
        baseline_digest=plan.baseline_digest,
        candidate_digest=plan.candidate_digest,
        protocol_digest=plan.protocol_digest,
        expected_cost_units=plan.expected_cost_units,
    ) if hypotheses else ()
    selected = executor.select_next(plans) if plans else None

    return {
        "experiment_id": plan.experiment_id,
        "runner_id": result.executor_id,
        "evaluator_id": evaluation.evaluator_id,
        "decision": evaluation.decision,
        "observation_outcome": outcome,
        "evaluation_recorded": True,
        "observation_recorded": True,
        "observation_id": observation_id,
        "evidence_event_id": source_event_id,
        "evidence_digest": source_digest,
        "diagnosis_ids": [item.diagnosis_id for item in diagnoses],
        "hypothesis_ids": [item.hypothesis_id for item in hypotheses],
        "selected_plan": ({
            "experiment_id": selected.experiment_id,
            "hypothesis_id": selected.hypothesis_id,
            "plan_digest": selected.plan_digest,
            "expected_cost_units": selected.expected_cost_units,
        } if selected else None),
        "execution_started": True,
        "authority": dict(_FORBIDDEN_AUTHORITY),
    }


__all__ = ["run_local_rsi_cycle"]
