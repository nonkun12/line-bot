from core.ai_factory_stage486_490_reproducibility_governance import (
    check_environment_stability, check_evaluator_disagreement,
    check_repeated_run_variance, check_reproduction_alignment,
    evaluate_stages_486_490,
)


def runs():
    common = {"protocol": "p1", "config": "c1", "dataset": "d1",
              "environment": "env1", "runtime": "py3", "score": 0.82}
    return [{"run_id": "r1", **common}, {"run_id": "r2", **common}]


def test_486_requires_matching_reproduction_fingerprints():
    assert check_reproduction_alignment(runs(),
        required_fields=["protocol", "config", "dataset"])["pass"]
    changed = runs()
    changed[1]["config"] = "c2"
    assert not check_reproduction_alignment(changed,
        required_fields=["protocol", "config", "dataset"])["pass"]


def test_487_bounds_repeated_run_variance():
    assert check_repeated_run_variance(runs(), score_field="score",
        maximum_spread=0.01, minimum_runs=2)["pass"]
    changed = runs()
    changed[1]["score"] = 0.9
    assert not check_repeated_run_variance(changed, score_field="score",
        maximum_spread=0.01, minimum_runs=2)["pass"]


def test_488_rejects_environment_drift():
    assert check_environment_stability(runs(),
        required_fields=["environment", "runtime"])["pass"]
    changed = runs()
    changed[1]["runtime"] = "py-other"
    assert not check_environment_stability(changed,
        required_fields=["environment", "runtime"])["pass"]


def test_489_detects_evaluator_verdict_conflict_and_threshold_inconsistency():
    rows = [{"evaluator_id": "a", "verdict": "PASS", "score": 0.9,
             "threshold": 0.8, "direction": "higher_is_better"},
            {"evaluator_id": "b", "verdict": "FAIL", "score": 0.7,
             "threshold": 0.8, "direction": "higher_is_better"}]
    assert not check_evaluator_disagreement(rows, minimum_evaluators=2)["pass"]
    aligned = [{**rows[0]}, {"evaluator_id": "b", "verdict": "PASS", "score": 0.85,
                            "threshold": 0.8, "direction": "higher_is_better"}]
    assert check_evaluator_disagreement(aligned, minimum_evaluators=2)["pass"]


def test_490_integrated_gate_fails_closed_and_never_authorizes_actions():
    result = evaluate_stages_486_490(
        reproduction_runs=runs(), reproduction_fields=["protocol", "config", "dataset"],
        maximum_score_spread=0.01, minimum_runs=2,
        environment_fields=["environment", "runtime"],
        evaluator_results=[
            {"evaluator_id": "a", "verdict": "PASS", "score": 0.9,
             "threshold": 0.8, "direction": "higher_is_better"},
            {"evaluator_id": "b", "verdict": "PASS", "score": 0.85,
             "threshold": 0.8, "direction": "higher_is_better"}],
        minimum_evaluators=2, splits={"train": ["a", "b"], "test": ["c"]},
        required_splits=["train", "test"],
        lineage_records=[{"dataset_id": "d", "version": "1", "parent_ref": "p"}],
        required_lineage_fields=["parent_ref"],
        calibration={"sample_count": 100, "error": 0.04, "method_id": "m",
                     "dataset_ref": "d", "evaluator_ref": "e"},
        minimum_calibration_samples=50, maximum_calibration_error=0.05,
        external_reference={"reference_id": "r", "source_id": "s", "version": "1",
            "retrieval_ref": "ref", "protocol_id": "p", "metric_id": "accuracy", "score": 0.8},
        expected_protocol_id="p", expected_metric_id="accuracy", unresolved_holds=[])
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["reproducibility_verified"] is False
    assert result["environment_authenticity_verified"] is False
    assert result["evaluator_independence_verified"] is False
    assert result["improvement_verified"] is False
    assert result["hold_release_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert result["merge_authorized"] is False
    assert result["deployment_authorized"] is False
    assert len(result["seal"]) == 64
