import math

from core.ai_factory_stage241_245_reproducibility_robustness import (
    stage241_reproducibility_check, stage242_stratified_robustness,
    stage243_safety_non_regression, stage244_gain_attribution,
    stage245_cycle_evidence_gate,
)

D1, D2, D3, D4 = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _runs():
    common = {"artifact_digest": D1, "protocol_digest": D2, "dataset_digest": D3,
              "suite_digest": D4, "environment_id": "env-a"}
    return [{**common, "run_id": f"r{i}", "primary_metric": 0.8} for i in range(3)]


def test_241_reproducibility_requires_same_inputs_unique_runs_and_bounded_spread():
    assert stage241_reproducibility_check(runs=_runs())["status"] == "REPRODUCIBLE"
    changed = _runs()
    changed[2]["environment_id"] = "env-b"
    assert stage241_reproducibility_check(runs=changed)["status"] == "INSUFFICIENT_EVIDENCE"
    spread = _runs()
    spread[2]["primary_metric"] = 0.9
    assert stage241_reproducibility_check(runs=spread)["status"] == "REPRODUCIBILITY_FAILED"
    duplicate = _runs()
    duplicate[1]["run_id"] = duplicate[0]["run_id"]
    assert stage241_reproducibility_check(runs=duplicate)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage241_reproducibility_check(runs=_runs(), held=True)["status"] == "INSUFFICIENT_EVIDENCE"


def test_242_robustness_requires_all_declared_strata_and_no_negative_slice():
    rows = [{"stratum_id": "a", "gain": 0.02, "sample_count": 10},
            {"stratum_id": "b", "gain": 0.01, "sample_count": 12}]
    assert stage242_stratified_robustness(strata=rows, required_strata=["a", "b"])["status"] == "ROBUSTNESS_SUPPORTED"
    assert stage242_stratified_robustness(strata=rows[:1], required_strata=["a", "b"])["status"] == "ROBUSTNESS_INSUFFICIENT"
    partial = stage242_stratified_robustness(strata=rows[:1], required_strata=["a", "b"], minimum_coverage=0.5)
    assert partial["status"] == "ROBUSTNESS_SUPPORTED"
    assert partial["missing_strata"] == ["b"]
    bad = [*rows[:1], {**rows[1], "gain": -0.1}]
    assert stage242_stratified_robustness(strata=bad, required_strata=["a", "b"])["status"] == "ROBUSTNESS_INSUFFICIENT"


def test_243_safety_non_regression_checks_every_metric_and_rejects_nonfinite():
    baseline = {"safety_score": 0.98, "incident_rate": 0.01}
    candidate = {"safety_score": 0.97, "incident_rate": 0.01}
    limits = {"safety_score": 0.02, "incident_rate": 0.0}
    assert stage243_safety_non_regression(baseline=baseline, candidate=candidate, metric_limits=limits)["status"] == "SAFETY_NON_REGRESSION_SUPPORTED"
    worse = {**candidate, "incident_rate": 0.02}
    assert stage243_safety_non_regression(baseline=baseline, candidate=worse, metric_limits=limits)["status"] == "SAFETY_REGRESSION_DETECTED"
    nan_map = {**candidate, "incident_rate": math.nan}
    assert stage243_safety_non_regression(baseline=baseline, candidate=nan_map, metric_limits=limits)["status"] == "INSUFFICIENT_EVIDENCE"


def _design():
    return {"design_type": "randomized_controlled", "treatment_group": "t", "control_group": "c",
            "assignment_method": "seeded random assignment", "preregistration_digest": D1}


def test_244_attribution_requires_controlled_design_independent_evaluator_and_positive_bound():
    args = {"design": _design(), "effect_estimate": 0.04, "lower_confidence_bound": 0.01,
            "evaluator_id": "eval-b", "independent_evaluator_id": "eval-b"}
    assert stage244_gain_attribution(**args)["status"] == "GAIN_ATTRIBUTION_SUPPORTED"
    assert stage244_gain_attribution(**{**args, "lower_confidence_bound": -0.01})["status"] == "GAIN_ATTRIBUTION_NOT_SUPPORTED"
    assert stage244_gain_attribution(**{**args, "evaluator_id": "eval-a"})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage244_gain_attribution(**{**args, "design": {**_design(), "design_type": "before_after"}})["status"] == "INSUFFICIENT_EVIDENCE"


def test_245_integrated_gate_is_review_only_and_fails_closed():
    good = {"reproducibility": {"status": "REPRODUCIBLE"},
            "robustness": {"status": "ROBUSTNESS_SUPPORTED"},
            "safety": {"status": "SAFETY_NON_REGRESSION_SUPPORTED"},
            "attribution": {"status": "GAIN_ATTRIBUTION_SUPPORTED"}}
    result = stage245_cycle_evidence_gate(**good)
    assert result["status"] == "CYCLE_EVIDENCE_READY_FOR_SEPARATE_REVIEW"
    assert result["task_execution_authorized"] is False
    assert result["experiment_execution_authorized"] is False
    assert result["model_change_authorized"] is False
    assert result["merge_deploy_authorized"] is False
    assert result["hold_release_authorized"] is False
    assert stage245_cycle_evidence_gate(**{**good, "safety": {"status": "SAFETY_REGRESSION_DETECTED"}})["status"] == "CYCLE_EVIDENCE_BLOCKED"
    assert stage245_cycle_evidence_gate(**good, held=True)["status"] == "INSUFFICIENT_EVIDENCE"
