from core.ai_factory_stage446_450_capability_evaluation import (
    check_baseline_alignment, check_capability_results, check_evaluation_protocol,
    check_regression_thresholds, evaluate_stages_446_450,
)


def protocol(version="2"):
    return {"protocol_id": "cap-eval", "version": version, "objective": "bounded task evaluation",
            "task_set_id": "tasks-v1", "scoring_method": "normalized-0-100", "owner": "eval-team",
            "tasks": [{"task_id": "t1"}, {"task_id": "t2"}],
            "score_bounds": {"min": 0, "max": 100}}


def baseline():
    return {**protocol("1"), "baseline_id": "baseline-2026"}


def test_446_requires_versioned_protocol_and_unique_task_set():
    assert check_evaluation_protocol(protocol())["pass"]
    assert not check_evaluation_protocol({**protocol(), "tasks": [{"task_id": "x"}, {"task_id": "x"}]})["pass"]


def test_447_requires_exact_task_coverage_bounded_scores_and_refs():
    p = protocol()
    good = [{"task_id": "t1", "score": 80, "result_ref": "run-1"},
            {"task_id": "t2", "score": 90, "result_ref": "run-2"}]
    assert check_capability_results(good, p)["pass"]
    assert not check_capability_results(good[:1], p)["pass"]
    assert not check_capability_results([{**good[0], "score": 101}, good[1]], p)["pass"]


def test_448_rejects_incomparable_baselines():
    assert check_baseline_alignment(protocol(), baseline())["pass"]
    assert not check_baseline_alignment(protocol(), {**baseline(), "task_set_id": "other"})["pass"]


def test_449_flags_only_drops_over_threshold():
    assert check_regression_thresholds(96, 100, 4)["pass"]
    assert check_regression_thresholds(95, 100, 5)["pass"]
    assert not check_regression_thresholds(94, 100, 5)["pass"]


def test_450_scorecard_is_bounded_and_never_authorizes_capability_claim():
    p, b = protocol(), baseline()
    result = evaluate_stages_446_450(
        protocol=p,
        results=[{"task_id": "t1", "score": 80, "result_ref": "run-1"},
                 {"task_id": "t2", "score": 90, "result_ref": "run-2"}],
        baseline_protocol=b, current_score=85, baseline_score=84, allowed_drop=2,
    )
    assert result["status"] == "PASS"
    assert result["capability_claim_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_446_450(
        protocol=p, results=[], baseline_protocol=b,
        current_score=70, baseline_score=90, allowed_drop=5,
    )
    assert blocked["status"] == "BLOCKED"
