from core.ai_factory_stage331_335_longitudinal_generalization import (
    stage331_check_temporal_window_stability,
    stage332_check_distribution_shift_robustness,
    stage333_check_bounded_measurement_perturbation,
    stage334_check_subgroup_gain_gap,
    stage335_integrate_longitudinal_generalization,
)


def temporal():
    return stage331_check_temporal_window_stability(
        window_gains={"w1": .3, "w2": .28, "w3": .32},
        minimum_window_gain=.1, maximum_window_spread=.1,
    )


def shift():
    return stage332_check_distribution_shift_robustness(
        shift_scenarios={
            "mild": {"shift_magnitude": .1, "gain": .2},
            "moderate": {"shift_magnitude": .3, "gain": .15},
        }, maximum_declared_shift=.4, minimum_shifted_gain=.1,
    )


def perturbation():
    return stage333_check_bounded_measurement_perturbation(
        task_gains={"a": .2, "b": .3, "c": .25},
        maximum_score_perturbation=.02, minimum_worst_case_gain=.1,
    )


def subgroup():
    return stage334_check_subgroup_gain_gap(
        subgroup_gains={"group_a": .2, "group_b": .25, "group_c": .22},
        minimum_subgroup_gain=.1, maximum_subgroup_gain_gap=.1,
    )


def test_331_temporal_windows_all_pass_and_spread_is_bounded():
    assert temporal()["status"] == "TEMPORAL_WINDOW_STABILITY_PASSED"
    assert stage331_check_temporal_window_stability(
        window_gains={"a": .3, "b": .02, "c": .3}, minimum_window_gain=.1,
    )["status"] == "TEMPORAL_WINDOW_STABILITY_FAILED"


def test_332_each_shift_scenario_must_pass():
    assert shift()["status"] == "DISTRIBUTION_SHIFT_ROBUST"
    assert stage332_check_distribution_shift_robustness(
        shift_scenarios={"bad": {"shift_magnitude": .8, "gain": .2}},
    )["status"] == "DISTRIBUTION_SHIFT_FRAGILE"


def test_333_worst_case_perturbation_must_pass():
    assert perturbation()["status"] == "BOUNDED_PERTURBATION_ROBUST"
    assert stage333_check_bounded_measurement_perturbation(
        task_gains={"a": .11, "b": .2}, maximum_score_perturbation=.02,
        minimum_worst_case_gain=.1,
    )["status"] == "BOUNDED_PERTURBATION_FRAGILE"


def test_334_subgroup_floor_and_gap_are_both_required():
    assert subgroup()["status"] == "SUBGROUP_GAIN_GAP_PASSED"
    assert stage334_check_subgroup_gain_gap(
        subgroup_gains={"a": .1, "b": .8}, minimum_subgroup_gain=.05,
        maximum_subgroup_gain_gap=.2,
    )["status"] == "SUBGROUP_GAIN_GAP_FAILED"


def test_335_integrated_gate_is_fail_closed_and_proposal_only():
    result = stage335_integrate_longitudinal_generalization(
        temporal_result=temporal(), shift_result=shift(),
        perturbation_result=perturbation(), subgroup_result=subgroup(),
    )
    assert result["status"] == "LONGITUDINAL_GENERALIZATION_PASSED"
    assert result["asi_demonstrated"] is False
    forged = dict(shift())
    forged["scenario_results"] = {"fake": {"gain": 999}}
    assert stage335_integrate_longitudinal_generalization(
        temporal_result=temporal(), shift_result=forged,
        perturbation_result=perturbation(), subgroup_result=subgroup(),
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage335_integrate_longitudinal_generalization(
        temporal_result=temporal(), shift_result=shift(),
        perturbation_result=perturbation(), subgroup_result=subgroup(), held=True,
    )["status"] == "INSUFFICIENT_EVIDENCE"
