import hashlib
import json

from core.ai_factory_stage256_260_paired_capability_evaluation import (
    stage256_preregister_evaluation, stage257_validate_paired_results,
    stage258_estimate_paired_gain, stage259_gate_capability_gain,
    stage260_capability_evidence_package,
)

TASKS = [
    {"task_id": f"task-{i:02d}", "task_digest": hashlib.sha256(f"task-{i}".encode()).hexdigest()}
    for i in range(30)
]
TASK_SET_DIGEST = hashlib.sha256(json.dumps(
    TASKS, sort_keys=True, separators=(",", ":")
).encode()).hexdigest()


def _pipeline(candidate_score=0.9):
    prereg = stage256_preregister_evaluation(
        protocol_id="protocol-001", metric_name="task_success",
        metric_direction="higher_is_better", minimum_gain=0.05,
        alpha=0.05, minimum_pairs=30, task_set_digest=TASK_SET_DIGEST,
    )
    rows = [{
        **task, "baseline_score": 0.7, "candidate_score": candidate_score
    } for task in TASKS]
    paired = stage257_validate_paired_results(preregistration=prereg, observations=rows)
    estimate = stage258_estimate_paired_gain(preregistration=prereg, paired_results=paired)
    gate = stage259_gate_capability_gain(preregistration=prereg, estimate=estimate)
    package = stage260_capability_evidence_package(
        preregistration=prereg, paired_results=paired, estimate=estimate, gate=gate)
    return prereg, paired, estimate, gate, package


def test_256_preregistration_freezes_threshold_and_task_set():
    result = stage256_preregister_evaluation(
        protocol_id="p", metric_name="accuracy", metric_direction="higher_is_better",
        minimum_gain=0.01, alpha=0.05, minimum_pairs=30, task_set_digest=TASK_SET_DIGEST)
    assert result["status"] == "EVALUATION_PREREGISTERED"
    assert result["task_execution_authorized"] is False
    assert stage256_preregister_evaluation(
        protocol_id="p", metric_name="accuracy", metric_direction="higher_is_better",
        minimum_gain=0, alpha=0.05, minimum_pairs=30, task_set_digest=TASK_SET_DIGEST
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage256_preregister_evaluation(
        protocol_id="p", metric_name="accuracy", metric_direction="higher_is_better",
        minimum_gain=0.01, alpha=0.5, minimum_pairs=30, task_set_digest=TASK_SET_DIGEST
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_257_requires_exact_unique_preregistered_task_pairs():
    prereg, *_ = _pipeline()
    rows = [{**task, "baseline_score": 0.7, "candidate_score": 0.8} for task in TASKS]
    assert stage257_validate_paired_results(preregistration=prereg, observations=rows)["status"] == "PAIRED_RESULTS_VALIDATED"
    assert stage257_validate_paired_results(
        preregistration=prereg, observations=rows[:-1] + [rows[0]]
    )["status"] == "INSUFFICIENT_EVIDENCE"
    changed = [dict(row) for row in rows]
    changed[0]["task_digest"] = "f" * 64
    assert stage257_validate_paired_results(preregistration=prereg, observations=changed)["status"] == "INSUFFICIENT_EVIDENCE"


def test_258_adjusts_for_metric_direction_and_produces_conservative_bound():
    prereg, paired, estimate, *_ = _pipeline()
    assert estimate["mean_gain"] > 0
    assert estimate["lower_bound"] <= estimate["mean_gain"] <= estimate["upper_bound"]
    lower_prereg = stage256_preregister_evaluation(
        protocol_id="lower", metric_name="latency", metric_direction="lower_is_better",
        minimum_gain=0.01, alpha=0.05, minimum_pairs=30, task_set_digest=TASK_SET_DIGEST)
    lower_rows = [{**task, "baseline_score": 0.8, "candidate_score": 0.6} for task in TASKS]
    lower_paired = stage257_validate_paired_results(preregistration=lower_prereg, observations=lower_rows)
    lower_estimate = stage258_estimate_paired_gain(preregistration=lower_prereg, paired_results=lower_paired)
    assert lower_estimate["mean_gain"] > 0


def test_259_requires_lower_bound_to_exceed_preregistered_minimum():
    *_, gate, package = _pipeline()
    assert gate["status"] == "CAPABILITY_GAIN_SUPPORTED"
    assert gate["model_change_authorized"] is False
    assert package["status"] == "CAPABILITY_EVIDENCE_PACKAGE_READY"
    assert package["rsi_or_asi_demonstrated"] is False
    assert package["requires_independent_replication"] is True
    *_, weak_gate, weak_package = _pipeline(candidate_score=0.71)
    assert weak_gate["status"] == "CAPABILITY_GAIN_NOT_ESTABLISHED"
    assert weak_package["status"] == "CAPABILITY_EVIDENCE_PACKAGE_READY"


def test_260_rejects_tampered_intermediate_evidence_and_held_state():
    prereg, paired, estimate, gate, _ = _pipeline()
    tampered = {**estimate, "mean_gain": 0.99}
    assert stage260_capability_evidence_package(
        preregistration=prereg, paired_results=paired, estimate=tampered, gate=gate
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage260_capability_evidence_package(
        preregistration=prereg, paired_results=paired, estimate=estimate,
        gate=gate, held=None
    )["status"] == "INSUFFICIENT_EVIDENCE"
