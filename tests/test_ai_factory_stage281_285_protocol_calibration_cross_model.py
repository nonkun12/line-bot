import hashlib
import json

from core.ai_factory_stage281_285_protocol_calibration_cross_model import (
    stage281_detect_protocol_drift, stage282_calibrate_evaluators,
    stage283_check_sample_adequacy, stage284_compare_cross_model_reproducibility,
    stage285_integrate_capability_evaluation,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def calibration():
    return stage282_calibrate_evaluators(calibration_rows=[
        {"evaluator_id": "eval-a", "item_id": f"i{i}", "score": 0.70 + i * 0.01,
         "reference_score": 0.70, "evidence_digest": digest(f"cal-{i}")}
        for i in range(3)
    ])


def samples():
    return stage283_check_sample_adequacy(task_records=[
        {"task_id": f"t{i}", "domain": "coding", "stratum": f"s{i % 2}",
         "task_digest": digest(f"task-{i}")}
        for i in range(30)
    ])


def cross_model():
    rows_a, rows_b = [], []
    for i in range(6):
        common = {"domain": "coding", "task_id": f"t{i}",
                  "evidence_digest": digest(f"paired-{i}")}
        rows_a.append({**common, "score": 0.70})
        rows_b.append({**common, "score": 0.72})
    task_digest = hashlib.sha256(json.dumps([f"t{i}" for i in range(6)], separators=(",", ":")).encode()).hexdigest()
    return stage284_compare_cross_model_reproducibility(
        model_a={"model_id": "model-a", "task_set_digest": task_digest, "scores": rows_a},
        model_b={"model_id": "model-b", "task_set_digest": task_digest, "scores": rows_b},
    )


def test_281_detects_protocol_drift_and_rejects_noncanonical_data():
    assert stage281_detect_protocol_drift(
        preregistered_protocol={"metric": "accuracy", "version": 1},
        observed_protocol={"metric": "accuracy", "version": 1},
    )["status"] == "PROTOCOL_UNCHANGED"
    assert stage281_detect_protocol_drift(
        preregistered_protocol={"metric": "accuracy", "version": 1},
        observed_protocol={"metric": "accuracy", "version": 2},
    )["status"] == "PROTOCOL_DRIFT_DETECTED"
    assert stage281_detect_protocol_drift(
        preregistered_protocol={"bad": float("nan")}, observed_protocol={"bad": 1}
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_282_calibrates_and_flags_inaccurate_evaluator():
    assert calibration()["status"] == "EVALUATORS_CALIBRATED"
    rows = [
        {"evaluator_id": "bad", "item_id": f"i{i}", "score": 0.1,
         "reference_score": 0.9, "evidence_digest": digest(f"bad-{i}")}
        for i in range(3)
    ]
    assert stage282_calibrate_evaluators(calibration_rows=rows)["status"] == "EVALUATOR_CALIBRATION_FAILED"


def test_283_requires_domain_task_and_stratum_coverage():
    assert samples()["status"] == "SAMPLE_ADEQUACY_PASSED"
    rows = [
        {"task_id": f"t{i}", "domain": "coding", "stratum": "only",
         "task_digest": digest(f"thin-{i}")}
        for i in range(30)
    ]
    assert stage283_check_sample_adequacy(task_records=rows)["status"] == "SAMPLE_ADEQUACY_FAILED"
    assert stage283_check_sample_adequacy(task_records=[*rows, rows[0]])["status"] == "INSUFFICIENT_EVIDENCE"


def test_284_requires_paired_task_rows_and_flags_model_gap():
    assert cross_model()["status"] == "CROSS_MODEL_REPRODUCIBILITY_WITHIN_LIMIT"
    task_ids = ["t1", "t2", "t3"]
    task_digest = hashlib.sha256(json.dumps(task_ids, separators=(",", ":")).encode()).hexdigest()
    rows_a = [{"domain": "coding", "task_id": task, "score": 0.1,
               "evidence_digest": digest(f"pair-{task}")} for task in task_ids]
    rows_b = [{"domain": "coding", "task_id": task, "score": 0.9,
               "evidence_digest": digest(f"pair-{task}")} for task in task_ids]
    result = stage284_compare_cross_model_reproducibility(
        model_a={"model_id": "a", "task_set_digest": task_digest, "scores": rows_a},
        model_b={"model_id": "b", "task_set_digest": task_digest, "scores": rows_b},
    )
    assert result["status"] == "CROSS_MODEL_REPRODUCIBILITY_FAILED"
    rows_b[0]["evidence_digest"] = digest("not-paired")
    assert stage284_compare_cross_model_reproducibility(
        model_a={"model_id": "a", "task_set_digest": task_digest, "scores": rows_a},
        model_b={"model_id": "b", "task_set_digest": task_digest, "scores": rows_b},
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_285_integrates_only_all_sealed_passing_evidence():
    protocol = stage281_detect_protocol_drift(
        preregistered_protocol={"metric": "accuracy", "v": 1},
        observed_protocol={"metric": "accuracy", "v": 1},
    )
    calibration_result, sample_result, cross_result = calibration(), samples(), cross_model()
    result = stage285_integrate_capability_evaluation(
        protocol_result=protocol, calibration_result=calibration_result,
        sample_result=sample_result, cross_model_result=cross_result,
    )
    assert result["status"] == "CAPABILITY_EVALUATION_EVIDENCE_INTEGRATED"
    assert result["general_capability_gain_proven"] is False
    assert result["experiment_execution_authorized"] is False
    tampered = {**protocol, "protocol_match": False}
    assert stage285_integrate_capability_evaluation(
        protocol_result=tampered, calibration_result=calibration_result,
        sample_result=sample_result, cross_model_result=cross_result,
    )["status"] == "INSUFFICIENT_EVIDENCE"
