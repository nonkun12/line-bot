from core.ai_factory_stage321_325_evaluator_task_robustness import (
    stage321_check_leave_one_evaluator_out,
    stage322_check_paired_task_gains,
    stage323_check_domain_gain_floors,
    stage324_check_cross_domain_gain_dispersion,
    stage325_integrate_task_evaluator_robustness,
)


def evaluator():
    return stage321_check_leave_one_evaluator_out(
        evaluator_gains={"e1": .2, "e2": .3, "e3": .25}, minimum_gain=.1
    )


def task():
    return stage322_check_paired_task_gains(
        task_scores={f"t{i}": {"baseline": .4, "candidate": .7} for i in range(10)},
        minimum_mean_gain=.1, minimum_positive_fraction=.8,
    )


def domain():
    return stage323_check_domain_gain_floors(
        domain_task_scores={
            "a": {f"a{i}": {"baseline": .4, "candidate": .7} for i in range(3)},
            "b": {f"b{i}": {"baseline": .5, "candidate": .8} for i in range(3)},
        }, minimum_domain_gain=.1,
    )


def dispersion():
    return stage324_check_cross_domain_gain_dispersion(
        domain_result=domain(), maximum_gain_spread=.1
    )


def test_321_leave_one_evaluator_out_gate():
    assert evaluator()["status"] == "LEAVE_ONE_EVALUATOR_OUT_ROBUST"
    assert stage321_check_leave_one_evaluator_out(
        evaluator_gains={"e1": 1.0, "e2": .2, "e3": -.5}, minimum_gain=.1
    )["status"] == "LEAVE_ONE_EVALUATOR_OUT_FRAGILE"
    assert stage321_check_leave_one_evaluator_out(
        evaluator_gains={"e1": .2, "e2": .3}
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_322_paired_task_gain_and_positive_fraction():
    assert task()["status"] == "PAIRED_TASK_GAINS_VALID"
    scores = {f"t{i}": {"baseline": .8, "candidate": .2} for i in range(10)}
    assert stage322_check_paired_task_gains(task_scores=scores)["status"] == "PAIRED_TASK_GAINS_BELOW_GATE"
    malformed = {f"t{i}": {"baseline": .4, "candidate": float("nan")} for i in range(10)}
    assert stage322_check_paired_task_gains(task_scores=malformed)["status"] == "INSUFFICIENT_EVIDENCE"


def test_323_every_domain_must_meet_gain_floor():
    assert domain()["status"] == "DOMAIN_GAIN_FLOORS_PASSED"
    weak = {"a": {"t1": {"baseline": .5, "candidate": .6},
                  "t2": {"baseline": .5, "candidate": .6},
                  "t3": {"baseline": .5, "candidate": .6}},
            "b": {"t1": {"baseline": .5, "candidate": .4},
                  "t2": {"baseline": .5, "candidate": .4},
                  "t3": {"baseline": .5, "candidate": .4}}}
    assert stage323_check_domain_gain_floors(domain_task_scores=weak)["status"] == "DOMAIN_GAIN_FLOOR_FAILED"


def test_324_cross_domain_dispersion_gate():
    assert dispersion()["status"] == "CROSS_DOMAIN_GAIN_SPREAD_PASSED"
    assert stage324_check_cross_domain_gain_dispersion(
        domain_result=domain(), maximum_gain_spread=.001
    )["status"] == "CROSS_DOMAIN_GAIN_SPREAD_FAILED"
    forged = dict(domain())
    forged["domain_results"] = {"x": {"mean_gain": .2}}
    assert stage324_check_cross_domain_gain_dispersion(
        domain_result=forged
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_325_integrated_robustness_gate_is_fail_closed():
    result = stage325_integrate_task_evaluator_robustness(
        evaluator_result=evaluator(), task_result=task(),
        domain_result=domain(), dispersion_result=dispersion(),
    )
    assert result["status"] == "TASK_EVALUATOR_ROBUSTNESS_PASSED"
    assert result["asi_demonstrated"] is False
    tampered = dict(task())
    tampered["mean_gain"] = 99
    assert stage325_integrate_task_evaluator_robustness(
        evaluator_result=evaluator(), task_result=tampered,
        domain_result=domain(), dispersion_result=dispersion(),
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage325_integrate_task_evaluator_robustness(
        evaluator_result=evaluator(), task_result=task(),
        domain_result=domain(), dispersion_result=dispersion(), held=True,
    )["status"] == "INSUFFICIENT_EVIDENCE"
