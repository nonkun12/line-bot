from core.ai_factory_stage456_460_robustness_uncertainty import (
    check_calibration_bins, check_perturbation_robustness, check_subgroup_coverage,
    check_uncertainty_summary, evaluate_stages_456_460,
)


def uncertainty():
    return {"sample_count": 100, "confidence_level": 0.95, "lower_bound": 0.7,
            "estimate": 0.8, "upper_bound": 0.9, "method": "bootstrap-declared"}


def test_456_checks_interval_and_confidence_declarations():
    assert check_uncertainty_summary(uncertainty())["pass"]
    assert not check_uncertainty_summary({**uncertainty(), "lower_bound": 0.85})["pass"]
    assert not check_uncertainty_summary({**uncertainty(), "confidence_level": 1.0})["pass"]


def test_457_requires_all_predeclared_groups_and_minimum_samples():
    rows = [{"group_id": "g1", "sample_count": 20}, {"group_id": "g2", "sample_count": 25}]
    assert check_subgroup_coverage(rows, required_groups=["g1", "g2"], minimum_samples=20)["pass"]
    assert not check_subgroup_coverage(rows[:1], required_groups=["g1", "g2"],
                                       minimum_samples=20)["pass"]


def test_458_requires_perturbation_scenario_coverage_and_threshold():
    rows = [{"scenario_id": "noise", "success_rate": 0.95},
            {"scenario_id": "format", "success_rate": 0.9}]
    assert check_perturbation_robustness(rows, required_scenarios=["noise", "format"],
                                         minimum_success_rate=0.9)["pass"]
    assert not check_perturbation_robustness(rows, required_scenarios=["noise", "format"],
                                             minimum_success_rate=0.91)["pass"]


def test_459_computes_weighted_calibration_error():
    bins = [{"count": 50, "mean_confidence": 0.8, "observed_accuracy": 0.8},
            {"count": 50, "mean_confidence": 0.9, "observed_accuracy": 0.8}]
    result = check_calibration_bins(bins, maximum_expected_calibration_error=0.05)
    assert result["pass"]
    assert abs(result["expected_calibration_error"] - 0.05) < 1e-12
    assert not check_calibration_bins(bins, maximum_expected_calibration_error=0.04)["pass"]


def test_460_aggregate_never_certifies_generalization_or_authorizes_execution():
    result = evaluate_stages_456_460(
        uncertainty=uncertainty(),
        subgroup_rows=[{"group_id": "g1", "sample_count": 20}],
        required_groups=["g1"], minimum_group_samples=20,
        perturbation_rows=[{"scenario_id": "noise", "success_rate": 0.95}],
        required_scenarios=["noise"], minimum_success_rate=0.9,
        calibration_bins=[{"count": 100, "mean_confidence": 0.8, "observed_accuracy": 0.8}],
        maximum_expected_calibration_error=0.05,
    )
    assert result["status"] == "PASS"
    assert result["statistical_validity_verified"] is False
    assert result["generalization_verified"] is False
    assert result["capability_claim_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
