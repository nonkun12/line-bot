"""Translate verified LoopLab evaluations into evidence-backed RSI observations.

This bridge records PASS/FAIL observations for hypothesis generation only.
BLOCKED evaluations are deliberately not promoted to observations. It never
runs candidates, executes plans, patches source, clears HOLD/STOP, or deploys.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any, Callable

from core.rsi_executor import Observation, RSIExecutor, canonical_digest
from core.rsi_experiment_protocol import evaluate_comparison

_FORBIDDEN_AUTHORITY = {
    "execution_authorized": False,
    "patch_authorized": False,
    "hold_clear_authorized": False,
    "stop_clear_authorized": False,
    "merge_deploy_authorized": False,
    "required_human_approval": True,
}


def record_evaluation_as_rsi_observation(
    *,
    evaluation_result: Mapping[str, Any],
    executor: RSIExecutor,
    producer_id: str,
    sign_digest: Callable[[str], str],
    created_at: int,
) -> dict[str, Any]:
    """Persist a signed, plan-bound observation for the existing RSI pipeline.

    Only independently recomputed PASS/FAIL evaluations can become
    observations. BLOCKED (and unknown) statuses are returned without writing
    to the RSI ledger. The RSI executor independently verifies source
    provenance and global control state before accepting the observation.
    """
    if not isinstance(evaluation_result, Mapping):
        raise ValueError("evaluation_result_must_be_object")
    status = evaluation_result.get("status")
    experiment_id = evaluation_result.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.strip() or len(experiment_id) > 100:
        raise ValueError("experiment_id_invalid")
    if status == "BLOCKED":
        return {
            "experiment_id": experiment_id,
            "status": "BLOCKED",
            "recorded": False,
            "reason": "blocked_evaluation_not_promoted_to_rsi_observation",
            "diagnosis_ids": [],
            "authority": dict(_FORBIDDEN_AUTHORITY),
        }
    if status not in {"PASS", "FAIL"}:
        raise ValueError("evaluation_status_not_eligible_for_rsi_observation")
    if not isinstance(producer_id, str) or not producer_id.strip() or len(producer_id) > 160:
        raise ValueError("producer_id_invalid")
    if type(created_at) is not int or created_at < 0:
        raise ValueError("created_at_invalid")
    if not callable(sign_digest):
        raise ValueError("independent_evidence_signer_required")

    record = evaluation_result.get("record")
    evaluation = evaluation_result.get("evaluation")
    if not isinstance(record, Mapping) or not isinstance(evaluation, Mapping):
        raise ValueError("evaluation_record_missing")
    if evaluation.get("status") != status:
        raise ValueError("evaluation_status_mismatch")
    if evaluation.get("experiment_id") != experiment_id:
        raise ValueError("evaluation_experiment_id_mismatch")
    if evaluation_result.get("adapter_id") != "looplab.simulator_rsi_bridge.v1":
        raise ValueError("untrusted_adapter_identity")
    baseline = record.get("baseline")
    challenger = record.get("challenger")
    held_out = record.get("held_out")
    evaluator = record.get("evaluator")
    if not all(isinstance(value, Mapping) for value in (baseline, challenger, held_out, evaluator)):
        raise ValueError("evaluation_record_schema_invalid")
    if record.get("experiment_id") != experiment_id:
        raise ValueError("record_experiment_id_mismatch")
    if held_out.get("locked") is not True:
        raise ValueError("held_out_fixture_not_locked")
    if evaluator.get("evaluator_id") != "rsi.exact_match.v1" or evaluator.get("version") != "1":
        raise ValueError("independent_evaluator_identity_mismatch")
    if baseline.get("candidate_id") == challenger.get("candidate_id"):
        raise ValueError("candidate_identity_collision")

    candidate_digest = challenger.get("artifact_sha256")
    result_digest = evaluation.get("evidence_sha256")
    if not isinstance(candidate_digest, str) or len(candidate_digest) != 64 or any(c not in "0123456789abcdef" for c in candidate_digest):
        raise ValueError("candidate_digest_invalid")
    if not isinstance(result_digest, str) or len(result_digest) != 64 or any(c not in "0123456789abcdef" for c in result_digest):
        raise ValueError("result_digest_invalid")
    canonical_record = json.dumps(dict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    recomputed = evaluate_comparison(record)
    if recomputed.get("status") != status:
        raise ValueError("evaluation_status_not_reproducible")
    if recomputed.get("experiment_id") != experiment_id:
        raise ValueError("evaluation_experiment_id_not_reproducible")
    if recomputed.get("evidence_sha256") != result_digest:
        raise ValueError("evaluation_evidence_digest_mismatch")
    if hashlib.sha256(canonical_record).hexdigest() != result_digest:
        raise ValueError("evaluation_record_digest_mismatch")
    protocol_digest = canonical_digest({"evaluator": dict(evaluator), "held_out": dict(held_out)})
    observation_id = f"looplab-{experiment_id}-{result_digest[:16]}"
    event_id = f"looplab-source-{experiment_id}-{result_digest[:16]}"
    observation = Observation(
        observation_id=observation_id,
        evidence_digest="0" * 64,
        capability="model",
        outcome=status,
        detail=str(evaluation.get("reason", status))[:2000],
        created_at=created_at,
        evidence_event_id=event_id,
        experiment_id=experiment_id,
        candidate_digest=candidate_digest,
        protocol_digest=protocol_digest,
        result_digest=result_digest,
    )
    evidence_digest = executor.ledger.append_observation_evidence(
        event_id,
        observation=observation,
        experiment_id=experiment_id,
        candidate_digest=candidate_digest,
        protocol_digest=protocol_digest,
        result_digest=result_digest,
        producer_id=producer_id,
        sign_digest=sign_digest,
    )
    from dataclasses import replace
    verified_observation = replace(observation, evidence_digest=evidence_digest)
    diagnoses = executor.observe((verified_observation,))
    hypotheses = executor.hypothesize(diagnoses) if diagnoses else ()
    plans = executor.plan(
        hypotheses,
        baseline_digest=baseline["artifact_sha256"],
        candidate_digest=candidate_digest,
        protocol_digest=protocol_digest,
        expected_cost_units=1,
    ) if hypotheses else ()
    selected = executor.select_next(plans) if plans else None
    return {
        "experiment_id": experiment_id,
        "status": status,
        "recorded": True,
        "observation_id": observation_id,
        "evidence_event_id": event_id,
        "evidence_digest": evidence_digest,
        "diagnosis_ids": [item.diagnosis_id for item in diagnoses],
        "hypothesis_ids": [item.hypothesis_id for item in hypotheses],
        "selected_plan": ({
            "experiment_id": selected.experiment_id,
            "hypothesis_id": selected.hypothesis_id,
            "plan_digest": selected.plan_digest,
            "expected_cost_units": selected.expected_cost_units,
        } if selected else None),
        "execution_started": False,
        "authority": dict(_FORBIDDEN_AUTHORITY),
    }


__all__ = ["record_evaluation_as_rsi_observation"]
