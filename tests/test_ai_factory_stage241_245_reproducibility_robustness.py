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
    return [{**common, "run_id": f"r{i}", "run_digest": chr(101+i) * 64,
             "primary_metric": 0.8} for i in range(3)]


def _identity():
    return stage241_reproducibility_check(runs=_runs())["identity_digest"]


def _design():
    return {"design_type": "randomized_controlled", "treatment_group": "t", "control_group": "c",
            "assignment_method": "randomized", "preregistration_digest": D2}


def _good_gates():
    identity = _identity()
    r = stage241_reproducibility_check(runs=_runs())
    s = stage242_stratified_robustness(
        strata=[{"stratum_id": "a", "gain": 0.02, "sample_count": 10},
                {"stratum_id": "b", "gain": 0.01, "sample_count": 12}],
        required_strata=["a", "b"], identity_digest=identity)
    safety = stage243_safety_non_regression(
        baseline={"safety_score": 0.98, "incident_rate": 0.01},
        candidate={"safety_score": 0.97, "incident_rate": 0.01},
        metric_limits={"safety_score": {"direction": "higher", "max_degradation": 0.02},
                       "incident_rate": {"direction": "lower", "max_degradation": 0.0}},
        identity_digest=identity)
    attribution = stage244_gain_attribution(
        design=_design(), effect_estimate=0.04, lower_confidence_bound=0.01,
        evaluator_id="eval", proposer_id="proposer", runner_id="runner",
        identity_digest=identity, protocol_digest=D2)
    return {"reproducibility": r, "robustness": s, "safety": safety, "attribution": attribution}


def test_241_requires_distinct_run_digests_and_rejects_invalid_bounds():
    assert stage241_reproducibility_check(runs=_runs())["status"] == "REPRODUCIBLE"
    duplicate = _runs()
    duplicate[1]["run_digest"] = duplicate[0]["run_digest"]
    assert stage241_reproducibility_check(runs=duplicate)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage241_reproducibility_check(runs=_runs(), required_runs=2)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage241_reproducibility_check(runs=_runs(), metric_tolerance=1e300)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage241_reproducibility_check(runs=_runs(), held=None)["status"] == "INSUFFICIENT_EVIDENCE"


def test_242_requires_complete_coverage_nonnegative_gain_and_minimum_samples():
    identity = _identity()
    rows = [{"stratum_id": "a", "gain": 0.02, "sample_count": 10},
            {"stratum_id": "b", "gain": 0.01, "sample_count": 12}]
    assert stage242_stratified_robustness(strata=rows, required_strata=["a", "b"],
                                          identity_digest=identity)["status"] == "ROBUSTNESS_SUPPORTED"
    assert stage242_stratified_robustness(strata=rows[:1], required_strata=["a", "b"],
                                          identity_digest=identity, minimum_coverage=0.5)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage242_stratified_robustness(strata=[{**rows[0], "gain": -5}],
                                          required_strata=["a"], identity_digest=identity)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage242_stratified_robustness(strata=[{**rows[0], "sample_count": 1}],
                                          required_strata=["a"], identity_digest=identity)["status"] == "INSUFFICIENT_EVIDENCE"


def test_243_direction_aware_safety_gate_detects_large_higher_is_better_drop():
    identity = _identity()
    limits = {"safety_score": {"direction": "higher", "max_degradation": 0.02},
              "incident_rate": {"direction": "lower", "max_degradation": 0.0}}
    result = stage243_safety_non_regression(
        baseline={"safety_score": 0.98, "incident_rate": 0.01},
        candidate={"safety_score": 0.0, "incident_rate": 0.01},
        metric_limits=limits, identity_digest=identity)
    assert result["status"] == "SAFETY_REGRESSION_DETECTED"
    improved = stage243_safety_non_regression(
        baseline={"safety_score": 0.98}, candidate={"safety_score": 1.0},
        metric_limits={"safety_score": {"direction": "higher", "max_degradation": 0.0}},
        identity_digest=identity)
    assert improved["status"] == "SAFETY_NON_REGRESSION_SUPPORTED"
    assert stage243_safety_non_regression(
        baseline={"x": 1}, candidate={"x": 2},
        metric_limits={"x": {"direction": "unknown", "max_degradation": 0}},
        identity_digest=identity)["status"] == "INSUFFICIENT_EVIDENCE"


def test_244_requires_distinct_roles_and_ordered_confidence_interval():
    args = {"design": _design(), "effect_estimate": 0.04, "lower_confidence_bound": 0.01,
            "evaluator_id": "eval", "proposer_id": "proposer", "runner_id": "runner",
            "identity_digest": _identity(), "protocol_digest": D2}
    assert stage244_gain_attribution(**args)["status"] == "GAIN_ATTRIBUTION_SUPPORTED"
    assert stage244_gain_attribution(**{**args, "runner_id": "eval"})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage244_gain_attribution(**{**args, "lower_confidence_bound": 0.5})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage244_gain_attribution(**{**args, "design": {**_design(), "assignment_method": "manual"}})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage244_gain_attribution(**{**args, "design": {**_design(), "assignment_method": "matched"}})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage244_gain_attribution(**{**args, "protocol_digest": D3})["status"] == "INSUFFICIENT_EVIDENCE"


def test_245_rejects_forged_statuses_mutation_and_identity_mismatch():
    good = _good_gates()
    assert stage245_cycle_evidence_gate(**good)["status"] == "CYCLE_EVIDENCE_READY_FOR_SEPARATE_REVIEW"
    forged = {key: {"status": status} for key, status in (
        ("reproducibility", "REPRODUCIBLE"), ("robustness", "ROBUSTNESS_SUPPORTED"),
        ("safety", "SAFETY_NON_REGRESSION_SUPPORTED"), ("attribution", "GAIN_ATTRIBUTION_SUPPORTED"))}
    assert stage245_cycle_evidence_gate(**forged)["status"] == "CYCLE_EVIDENCE_BLOCKED"
    tampered = dict(good)
    tampered["safety"] = {**good["safety"], "metric_degradations": {"safety_score": 999}}
    assert stage245_cycle_evidence_gate(**tampered)["status"] == "CYCLE_EVIDENCE_BLOCKED"
    mismatched = dict(good)
    mismatched["robustness"] = {**good["robustness"], "identity_digest": D4}
    assert stage245_cycle_evidence_gate(**mismatched)["status"] == "CYCLE_EVIDENCE_BLOCKED"
    assert stage245_cycle_evidence_gate(**good, held=None)["status"] == "INSUFFICIENT_EVIDENCE"
