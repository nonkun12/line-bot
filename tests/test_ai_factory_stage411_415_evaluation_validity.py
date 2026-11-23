from core.ai_factory_stage411_415_evaluation_validity import (
    check_comparison_compatibility, check_metric_denominators,
    check_metric_specifications, check_uncertainty_intervals,
    evaluate_stages_411_415,
)


def test_stage_411_requires_interpretable_unique_metric_specs():
    assert check_metric_specifications([{
        "metric_id": "latency", "definition": "p95 request latency",
        "unit": "ms", "direction": "lower_is_better", "aggregation": "median",
    }])["pass"]
    bad = check_metric_specifications([
        {"metric_id": "x", "definition": "", "unit": "ms",
         "direction": "unknown", "aggregation": "mean"},
        {"metric_id": "x", "definition": "duplicate", "unit": "ms",
         "direction": "higher_is_better", "aggregation": "mean"},
    ])
    assert not bad["pass"]
    assert "metric_id_duplicate:x" in bad["errors"]


def test_stage_412_checks_denominator_arithmetic_and_sample_coverage():
    assert check_metric_denominators([{
        "metric_id": "success", "cohort_id": "a", "numerator": 8,
        "denominator": 10, "sample_count": 10,
    }])["pass"]
    bad = check_metric_denominators([{
        "metric_id": "success", "cohort_id": "a", "numerator": 11,
        "denominator": 10, "sample_count": 9,
    }])
    assert not bad["pass"]
    assert "numerator_exceeds_denominator:success:a" in bad["errors"]
    assert "sample_count_below_denominator:success:a" in bad["errors"]


def test_stage_413_requires_finite_ordered_uncertainty_bounds():
    assert check_uncertainty_intervals([{
        "metric_id": "quality", "cohort_id": "a", "lower": 0.7,
        "estimate": 0.8, "upper": 0.9, "method": "declared bootstrap",
    }])["pass"]
    bad = check_uncertainty_intervals([{
        "metric_id": "quality", "cohort_id": "a", "lower": 0.9,
        "estimate": 0.8, "upper": float("inf"), "method": "",
    }])
    assert not bad["pass"]
    assert "interval_value_nonfinite_or_invalid:quality:a" in bad["errors"]


def test_stage_414_rejects_incomparable_study_contexts():
    item = {
        "metric_id": "quality", "cohort_id": "a",
        "baseline_protocol": "v1", "candidate_protocol": "v1",
        "baseline_population": "users-a", "candidate_population": "users-a",
        "baseline_window": "week-1", "candidate_window": "week-1",
    }
    assert check_comparison_compatibility([item])["pass"]
    bad = {**item, "candidate_population": "users-b"}
    result = check_comparison_compatibility([bad])
    assert not result["pass"]
    assert "comparison_population_mismatch:quality:a" in result["errors"]


def test_stage_415_fails_closed_and_never_grants_authority():
    args = dict(
        metric_specifications=[{
            "metric_id": "success", "definition": "success rate", "unit": "ratio",
            "direction": "higher_is_better", "aggregation": "rate",
        }],
        observations=[{"metric_id": "success", "cohort_id": "a", "numerator": 8,
                       "denominator": 10, "sample_count": 10}],
        uncertainty_intervals=[{"metric_id": "success", "cohort_id": "a",
                                "lower": 0.7, "estimate": 0.8, "upper": 0.9,
                                "method": "declared interval method"}],
        comparisons=[{"metric_id": "success", "cohort_id": "a",
                      "baseline_protocol": "v1", "candidate_protocol": "v1",
                      "baseline_population": "users-a", "candidate_population": "users-a",
                      "baseline_window": "week-1", "candidate_window": "week-1"}],
    )
    passed = evaluate_stages_411_415(**args)
    assert passed["status"] == "PASS"
    assert passed["proposal_only"] is True
    assert passed["execution_authorized"] is False
    assert passed["promotion_authorized"] is False
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_411_415(**{**args, "observations": []})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
    assert blocked["promotion_authorized"] is False
