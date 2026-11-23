from core.ai_factory_stage326_330_measurement_sensitivity import (
    stage326_check_evaluator_coalition_ablation,
    stage327_check_task_difficulty_strata,
    stage328_check_gain_threshold_sensitivity,
    stage329_check_weight_concentration,
    stage330_integrate_measurement_sensitivity,
)


def coalition():
    return stage326_check_evaluator_coalition_ablation(
        evaluator_gains={"e1": .4, "e2": .5, "e3": .45, "e4": .42},
        maximum_removed=2, minimum_remaining_gain=.1,
    )


def strata():
    return stage327_check_task_difficulty_strata(
        strata_scores={
            "easy": {f"e{i}": {"baseline": .3, "candidate": .6} for i in range(3)},
            "hard": {f"h{i}": {"baseline": .2, "candidate": .4} for i in range(3)},
        }, minimum_stratum_gain=.1,
    )


def threshold():
    return stage328_check_gain_threshold_sensitivity(
        task_gains={f"t{i}": .3 + i * .01 for i in range(10)},
        gain_thresholds=[.1, .2], minimum_positive_fraction=.8,
    )


def weights():
    return stage329_check_weight_concentration(
        weighted_task_gains={f"t{i}": {"gain": .3, "weight": 1.0} for i in range(4)},
        maximum_weight_share=.3, minimum_weighted_gain=.1,
    )


def test_326_coalition_ablation_checks_multi_evaluator_removals():
    assert coalition()["status"] == "EVALUATOR_COALITION_ROBUST"
    assert stage326_check_evaluator_coalition_ablation(
        evaluator_gains={"a": 1, "b": .2, "c": -.8}, maximum_removed=2,
        minimum_remaining_gain=.1,
    )["status"] == "EVALUATOR_COALITION_FRAGILE"
    assert stage326_check_evaluator_coalition_ablation(
        evaluator_gains={"a": .2, "b": .3}, maximum_removed=1,
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_327_each_difficulty_stratum_must_pass():
    assert strata()["status"] == "TASK_DIFFICULTY_STRATA_PASSED"
    weak = {"easy": {f"e{i}": {"baseline": .2, "candidate": .5} for i in range(3)},
            "hard": {f"h{i}": {"baseline": .5, "candidate": .4} for i in range(3)}}
    assert stage327_check_task_difficulty_strata(strata_scores=weak)["status"] == "TASK_DIFFICULTY_STRATA_FAILED"


def test_328_all_gain_thresholds_must_pass():
    assert threshold()["status"] == "GAIN_THRESHOLD_SENSITIVITY_PASSED"
    assert stage328_check_gain_threshold_sensitivity(
        task_gains={"a": .05, "b": .1}, gain_thresholds=[.2],
    )["status"] == "GAIN_THRESHOLD_SENSITIVITY_FAILED"
    assert stage328_check_gain_threshold_sensitivity(
        task_gains={"a": .2}, gain_thresholds=[.1, .1],
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_329_weight_concentration_and_weighted_gain():
    assert weights()["status"] == "WEIGHT_CONCENTRATION_PASSED"
    concentrated = {"a": {"gain": .5, "weight": 9}, "b": {"gain": .5, "weight": 1}}
    assert stage329_check_weight_concentration(
        weighted_task_gains=concentrated, maximum_weight_share=.8,
    )["status"] == "WEIGHT_CONCENTRATION_FAILED"


def test_330_integrated_gate_is_sealed_and_proposal_only():
    result = stage330_integrate_measurement_sensitivity(
        coalition_result=coalition(), strata_result=strata(),
        threshold_result=threshold(), weight_result=weights(),
    )
    assert result["status"] == "MEASUREMENT_SENSITIVITY_PASSED"
    assert result["asi_demonstrated"] is False
    altered = dict(weights())
    altered["weighted_mean_gain"] = 999
    assert stage330_integrate_measurement_sensitivity(
        coalition_result=coalition(), strata_result=strata(),
        threshold_result=threshold(), weight_result=altered,
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage330_integrate_measurement_sensitivity(
        coalition_result=coalition(), strata_result=strata(),
        threshold_result=threshold(), weight_result=weights(), held=True,
    )["status"] == "INSUFFICIENT_EVIDENCE"
