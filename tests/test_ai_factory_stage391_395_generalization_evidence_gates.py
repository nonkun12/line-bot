from core.ai_factory_stage391_395_generalization_evidence_gates import (
    check_cohort_replicates, check_guardrail_coverage, check_slice_coverage,
    check_worst_case_improvement, evaluate_stages_391_395,
)


def test_stage_391_requires_exact_slice_coverage_and_minimum_counts():
    good = check_slice_coverage(
        [{"slice_id": "a", "sample_count": 20}, {"slice_id": "b", "sample_count": 20}],
        required_slice_ids=["a", "b"], minimum_samples_per_slice=10)
    assert good["pass"]
    bad = check_slice_coverage(
        [{"slice_id": "a", "sample_count": 2}, {"slice_id": "a", "sample_count": 20}],
        required_slice_ids=["a", "b"], minimum_samples_per_slice=10)
    assert not bad["pass"]
    assert "slice_id_duplicate:a" in bad["errors"]
    assert "slice_missing:b" in bad["errors"]


def test_stage_392_enforces_worst_case_not_average_improvement():
    assert check_worst_case_improvement([0.2, 0.1], minimum_improvement=0.05)["pass"]
    result = check_worst_case_improvement([0.2, -0.01], minimum_improvement=0.0)
    assert not result["pass"]
    assert result["worst_case_improvement"] == -0.01


def test_stage_393_requires_all_guardrails_and_checks_direction():
    good = check_guardrail_coverage([
        {"guardrail_id": "latency", "baseline": 100, "current": 105,
         "direction": "lower", "maximum_regression": 10},
        {"guardrail_id": "quality", "baseline": 0.8, "current": 0.79,
         "direction": "higher", "maximum_regression": 0.02},
    ], required_guardrail_ids=["latency", "quality"])
    assert good["pass"]
    bad = check_guardrail_coverage([
        {"guardrail_id": "latency", "baseline": 100, "current": 120,
         "direction": "lower", "maximum_regression": 10},
    ], required_guardrail_ids=["latency", "quality"])
    assert not bad["pass"]
    assert "guardrail_regression_exceeded:latency" in bad["errors"]
    assert "guardrail_missing:quality" in bad["errors"]


def test_stage_394_requires_unique_cohorts_and_minimum_improvement():
    assert check_cohort_replicates([
        {"cohort_id": "c1", "improvement": 0.1},
        {"cohort_id": "c2", "improvement": 0.08},
    ], minimum_cohorts=2, minimum_improvement=0.05)["pass"]
    bad = check_cohort_replicates([
        {"cohort_id": "c1", "improvement": 0.1},
        {"cohort_id": "c1", "improvement": 0.01},
    ], minimum_cohorts=2, minimum_improvement=0.05)
    assert not bad["pass"]
    assert "cohort_id_duplicate:c1" in bad["errors"]
    assert "cohort_count_below_minimum" in bad["errors"]


def test_stage_395_aggregates_and_never_authorizes_execution_or_promotion():
    args = dict(
        slices=[{"slice_id": "a", "sample_count": 20}, {"slice_id": "b", "sample_count": 20}],
        required_slice_ids=["a", "b"], minimum_samples_per_slice=10,
        slice_improvements=[0.1, 0.08], minimum_worst_case_improvement=0.05,
        guardrails=[{"guardrail_id": "latency", "baseline": 100, "current": 105,
                     "direction": "lower", "maximum_regression": 10}],
        required_guardrail_ids=["latency"],
        cohorts=[{"cohort_id": "c1", "improvement": 0.1},
                 {"cohort_id": "c2", "improvement": 0.08}],
        minimum_cohorts=2, minimum_cohort_improvement=0.05,
    )
    passed = evaluate_stages_391_395(**args)
    assert passed["status"] == "PASS"
    assert passed["proposal_only"] is True
    assert passed["execution_authorized"] is False
    assert passed["promotion_authorized"] is False
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_391_395(**{**args, "slice_improvements": [0.1, -0.1]})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
    assert blocked["promotion_authorized"] is False
