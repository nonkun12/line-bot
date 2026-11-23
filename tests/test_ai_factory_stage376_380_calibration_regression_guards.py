from core.ai_factory_stage376_380_calibration_regression_guards import (
    check_calibration_bins,
    check_confidence_intervals,
    check_metric_regressions,
    check_subgroup_disparity,
    evaluate_stages_376_380,
)


def test_stage_376_weighted_calibration_error_is_bounded():
    result = check_calibration_bins([
        {"count": 10, "confidence": 0.8, "accuracy": 0.7},
        {"count": 10, "confidence": 0.5, "accuracy": 0.5},
    ], maximum_expected_error=0.05)
    assert result["pass"]
    assert result["expected_calibration_error"] == 0.05
    blocked = check_calibration_bins(
        [{"count": 10, "confidence": 0.9, "accuracy": 0.6}],
        maximum_expected_error=0.1,
    )
    assert "expected_calibration_error_exceeded" in blocked["errors"]


def test_stage_377_rejects_malformed_or_out_of_range_intervals():
    assert check_confidence_intervals([
        {"lower": 0.2, "estimate": 0.5, "upper": 0.8}
    ])["pass"]
    result = check_confidence_intervals([
        {"lower": 0.8, "estimate": 0.5, "upper": 0.2},
        {"lower": 0.0, "estimate": 0.9, "upper": 0.8},
    ])
    assert not result["pass"]
    assert "interval_order_invalid:0" in result["errors"]
    assert "estimate_outside_interval:1" in result["errors"]


def test_stage_378_enforces_minimum_group_size_and_gap():
    assert check_subgroup_disparity([
        {"size": 20, "score": 0.8}, {"size": 20, "score": 0.7}
    ], maximum_gap=0.1, minimum_group_size=10)["pass"]
    result = check_subgroup_disparity([
        {"size": 5, "score": 0.9}, {"size": 20, "score": 0.5}
    ], maximum_gap=0.2, minimum_group_size=10)
    assert not result["pass"]
    assert "group_below_minimum_size:0" in result["errors"]
    assert "subgroup_gap_exceeded" in result["errors"]


def test_stage_379_checks_directional_metric_regression():
    assert check_metric_regressions([
        {"baseline": 0.8, "current": 0.79, "direction": "higher", "maximum_regression": 0.02},
        {"baseline": 10, "current": 11, "direction": "lower", "maximum_regression": 1},
    ])["pass"]
    result = check_metric_regressions([
        {"baseline": 0.8, "current": 0.7, "direction": "higher", "maximum_regression": 0.05}
    ])
    assert not result["pass"]
    assert "metric_regression_exceeded:0" in result["errors"]


def test_stage_380_aggregates_guards_and_never_authorizes_execution():
    args = dict(
        calibration_bins=[{"count": 10, "confidence": 0.8, "accuracy": 0.8}],
        maximum_expected_error=0.05,
        confidence_intervals=[{"lower": 0.4, "estimate": 0.5, "upper": 0.6}],
        subgroups=[{"size": 20, "score": 0.8}, {"size": 20, "score": 0.75}],
        maximum_subgroup_gap=0.1, minimum_group_size=10,
        metrics=[{"baseline": 0.8, "current": 0.79, "direction": "higher", "maximum_regression": 0.02}],
    )
    passed = evaluate_stages_376_380(**args)
    assert passed["status"] == "PASS"
    assert passed["execution_authorized"] is False
    assert passed["proposal_only"] is True
    assert len(passed["seal"]) == 64

    blocked = evaluate_stages_376_380(**{**args, "calibration_bins": [{"count": 10, "confidence": 0.9, "accuracy": 0.6}]})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
