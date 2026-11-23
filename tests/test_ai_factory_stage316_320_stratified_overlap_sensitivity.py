import hashlib

from core.ai_factory_stage316_320_stratified_overlap_sensitivity import (
    stage316_check_stratified_sampling,
    stage317_check_evaluator_overlap,
    stage318_check_evaluator_domain_coverage,
    stage319_check_attrition_sensitivity,
    stage320_integrate_stratified_overlap_sensitivity,
)


def sampling():
    return stage316_check_stratified_sampling(
        task_strata={"t1": "a", "t2": "a", "t3": "b", "t4": "b"},
        inclusion_probabilities={"t1": .5, "t2": .5, "t3": .4, "t4": .4},
    )


def overlap():
    return stage317_check_evaluator_overlap(
        evaluator_tasks={"e1": ["t1", "t2"], "e2": ["t1", "t3"]},
        minimum_shared_tasks=1, maximum_pairwise_jaccard=.5,
    )


def coverage():
    return stage318_check_evaluator_domain_coverage(
        evaluator_domain_counts={
            "e1": {"a": 2, "b": 1}, "e2": {"a": 1, "b": 2}
        }, required_domains=["a", "b"],
    )


def sensitivity():
    return stage319_check_attrition_sensitivity(
        baseline_observed_scores=[.5] * 10, candidate_observed_scores=[.8] * 10,
        baseline_missing_count=0, candidate_missing_count=0,
        minimum_tasks=10, minimum_worst_case_gain=.1,
    )


def test_316_stratified_sampling_coverage_and_probability():
    assert sampling()["status"] == "STRATIFIED_SAMPLING_VALID"
    assert stage316_check_stratified_sampling(
        task_strata={"t1": "a", "t2": "b"},
        inclusion_probabilities={"t1": .5, "t2": .5},
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage316_check_stratified_sampling(
        task_strata={"t1": "a", "t2": "a"},
        inclusion_probabilities={"t1": 0, "t2": .5},
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_317_pairwise_evaluator_overlap_bounds():
    assert overlap()["status"] == "EVALUATOR_OVERLAP_WITHIN_BOUNDS"
    assert stage317_check_evaluator_overlap(
        evaluator_tasks={"e1": ["x", "y"], "e2": ["x", "y"]},
        maximum_pairwise_jaccard=.5,
    )["status"] == "EVALUATOR_OVERLAP_OUT_OF_BOUNDS"
    assert stage317_check_evaluator_overlap(
        evaluator_tasks={"e1": ["x"], "e2": ["y"]}, minimum_shared_tasks=1,
    )["status"] == "EVALUATOR_OVERLAP_OUT_OF_BOUNDS"


def test_318_required_domain_evaluator_coverage():
    assert coverage()["status"] == "EVALUATOR_DOMAIN_COVERAGE_VALID"
    assert stage318_check_evaluator_domain_coverage(
        evaluator_domain_counts={"e1": {"a": 2}, "e2": {"a": 1}},
        required_domains=["a", "b"],
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_319_worst_case_attrition_sensitivity():
    assert sensitivity()["status"] == "ATTRITION_SENSITIVITY_ROBUST"
    result = stage319_check_attrition_sensitivity(
        baseline_observed_scores=[.8] * 9, candidate_observed_scores=[.9] * 9,
        baseline_missing_count=1, candidate_missing_count=1,
        minimum_tasks=10, minimum_worst_case_gain=.0,
    )
    assert result["status"] == "ATTRITION_SENSITIVITY_NOT_ROBUST"
    assert stage319_check_attrition_sensitivity(
        baseline_observed_scores=[.5], candidate_observed_scores=[.7],
        baseline_missing_count=0, candidate_missing_count=1,
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_320_integrates_only_sealed_passing_gates():
    result = stage320_integrate_stratified_overlap_sensitivity(
        sampling_result=sampling(), overlap_result=overlap(),
        coverage_result=coverage(), sensitivity_result=sensitivity(),
    )
    assert result["status"] == "STRATIFIED_OVERLAP_SENSITIVITY_PASSED"
    assert result["asi_demonstrated"] is False
    tampered = dict(sampling())
    tampered["task_count"] = 999
    assert stage320_integrate_stratified_overlap_sensitivity(
        sampling_result=tampered, overlap_result=overlap(),
        coverage_result=coverage(), sensitivity_result=sensitivity(),
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage320_integrate_stratified_overlap_sensitivity(
        sampling_result=sampling(), overlap_result=overlap(),
        coverage_result=coverage(), sensitivity_result=sensitivity(), held=True,
    )["status"] == "INSUFFICIENT_EVIDENCE"
