from core.ai_factory_stage471_475_longitudinal_improvement import (
    check_evaluator_consensus, check_history_completeness, check_regression_trend,
    check_sustained_performance, evaluate_stages_471_475,
)


def history():
    return [{"cycle_id": "c1", "sequence": 1, "baseline_ref": "b1",
             "candidate_ref": "n1", "evaluation_ref": "e1"},
            {"cycle_id": "c2", "sequence": 2, "baseline_ref": "b2",
             "candidate_ref": "n2", "evaluation_ref": "e2"}]


def test_471_requires_complete_ordered_unique_history():
    assert check_history_completeness(history(), expected_cycles=2)["pass"]
    assert not check_history_completeness(history()[:1], expected_cycles=2)["pass"]
    duplicated = [history()[0], {**history()[1], "sequence": 1}]
    assert not check_history_completeness(duplicated, expected_cycles=2)["pass"]


def test_472_requires_sustained_trailing_passes():
    assert check_sustained_performance([0.8, 0.82, 0.83], minimum_cycles=3,
        minimum_score=0.8, required_consecutive_passes=2)["pass"]
    assert not check_sustained_performance([0.8, 0.7, 0.83], minimum_cycles=3,
        minimum_score=0.8, required_consecutive_passes=2)["pass"]


def test_473_detects_trailing_regression():
    assert check_regression_trend([0.8, 0.82, 0.81], maximum_drop=0.05,
                                  window_size=3)["pass"]
    assert not check_regression_trend([0.9, 0.8, 0.7], maximum_drop=0.1,
                                      window_size=3)["pass"]


def test_474_requires_distinct_evaluators_and_bounded_spread():
    rows = [{"evaluator_id": "e1", "score": 0.8},
            {"evaluator_id": "e2", "score": 0.82}]
    assert check_evaluator_consensus(rows, minimum_evaluators=2,
                                     maximum_spread=0.05)["pass"]
    assert not check_evaluator_consensus([rows[0], rows[0]], minimum_evaluators=2,
                                         maximum_spread=0.05)["pass"]


def test_475_aggregate_holds_on_failure_and_never_certifies_improvement():
    result = evaluate_stages_471_475(
        history=history(), expected_cycles=2, cycle_scores=[0.8, 0.82],
        minimum_cycles=2, minimum_score=0.8, required_consecutive_passes=2,
        maximum_drop=0.05, trend_window_size=2,
        evaluator_results=[{"evaluator_id": "e1", "score": 0.8},
                           {"evaluator_id": "e2", "score": 0.82}],
        minimum_evaluators=2, maximum_evaluator_spread=0.05)
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["longitudinal_improvement_verified"] is False
    assert result["evaluator_independence_verified"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
