from core.ai_factory_stage461_465_improvement_attribution import (
    check_change_isolation, check_guardrail_metrics, check_metric_improvement,
    check_paired_comparison, evaluate_stages_461_465,
)


def pair():
    base = {"run_id": "base-1", "protocol_id": "p", "task_set_id": "tasks",
            "metric_id": "accuracy", "scoring_method": "ratio", "metric_value": 0.8}
    candidate = {**base, "run_id": "candidate-1", "metric_value": 0.85}
    return base, candidate


def test_461_requires_matched_comparison_context():
    a, b = pair()
    assert check_paired_comparison(a, b)["pass"]
    assert not check_paired_comparison(a, {**b, "task_set_id": "other"})["pass"]


def test_462_rejects_uncontrolled_or_multiple_primary_changes():
    assert check_change_isolation([{"change_id": "c1", "category": "prompt"}], "prompt")["pass"]
    assert not check_change_isolation([
        {"change_id": "c1", "category": "prompt"},
        {"change_id": "c2", "category": "weights"}], "prompt")["pass"]


def test_463_respects_metric_direction_and_minimum_gain():
    assert check_metric_improvement(0.8, 0.85, direction="higher_is_better",
                                    minimum_improvement=0.05)["pass"]
    assert check_metric_improvement(100, 95, direction="lower_is_better",
                                    minimum_improvement=5)["pass"]
    assert not check_metric_improvement(0.8, 0.81, direction="higher_is_better",
                                        minimum_improvement=0.05)["pass"]


def test_464_fails_when_guardrail_regression_exceeds_limit():
    assert check_guardrail_metrics({"latency": 10}, {"latency": 11}, {"latency": 1})["pass"]
    assert not check_guardrail_metrics({"latency": 10}, {"latency": 12}, {"latency": 1})["pass"]


def test_465_aggregate_holds_on_any_failed_gate_and_never_authorizes():
    a, b = pair()
    args = dict(baseline=a, candidate=b,
        changes=[{"change_id": "c1", "category": "prompt"}],
        declared_primary_change="prompt", direction="higher_is_better",
        minimum_improvement=0.05, guardrail_baseline={"latency": 10},
        guardrail_candidate={"latency": 10.5}, maximum_regressions={"latency": 1})
    result = evaluate_stages_461_465(**args)
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["causal_attribution_verified"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    args["candidate"] = {**b, "metric_value": 0.81}
    assert evaluate_stages_461_465(**args)["status"] == "HOLD"
