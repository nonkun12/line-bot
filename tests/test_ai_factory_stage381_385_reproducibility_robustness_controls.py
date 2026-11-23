from core.ai_factory_stage381_385_reproducibility_robustness_controls import (
    check_perturbation_coverage,
    check_repeat_run_stability,
    check_reproducibility_manifest,
    check_sensitivity_bounds,
    evaluate_stages_381_385,
)


def test_stage_381_requires_complete_reproducibility_manifest():
    good = {
        "code_digest": "c", "config_digest": "f", "data_digest": "d",
        "seed": 0, "environment_digest": "e",
    }
    assert check_reproducibility_manifest(good)["pass"]
    result = check_reproducibility_manifest({**good, "data_digest": ""})
    assert not result["pass"]
    assert "manifest_field_missing:data_digest" in result["errors"]


def test_stage_382_requires_exact_perturbation_coverage():
    assert check_perturbation_coverage(["noise", "dropout"], ["dropout", "noise"])["pass"]
    result = check_perturbation_coverage(["noise", "dropout"], ["noise", "latency"])
    assert not result["pass"]
    assert result["missing"] == ["dropout"]
    assert result["unexpected"] == ["latency"]


def test_stage_383_bounds_absolute_sensitivity():
    assert check_sensitivity_bounds(
        [{"baseline": 0.8, "perturbed": 0.75}], maximum_absolute_change=0.05
    )["pass"]
    result = check_sensitivity_bounds(
        [{"baseline": 0.8, "perturbed": 0.6}], maximum_absolute_change=0.1
    )
    assert not result["pass"]
    assert "sensitivity_bound_exceeded:0" in result["errors"]


def test_stage_384_bounds_repeat_run_range():
    assert check_repeat_run_stability([0.8, 0.81, 0.79], maximum_range=0.02)["pass"]
    result = check_repeat_run_stability([0.8, 0.9], maximum_range=0.05)
    assert not result["pass"]
    assert "repeat_run_range_exceeded" in result["errors"]
    assert "at_least_two_repeats_required" in check_repeat_run_stability(
        [0.8], maximum_range=0.1
    )["errors"]


def test_stage_385_aggregates_and_never_authorizes_execution():
    args = dict(
        manifest={"code_digest": "c", "config_digest": "f", "data_digest": "d",
                  "seed": 42, "environment_digest": "e"},
        required_perturbations=["noise", "dropout"],
        observed_perturbations=["noise", "dropout"],
        sensitivity_observations=[{"baseline": 0.8, "perturbed": 0.78}],
        maximum_absolute_change=0.05,
        repeat_scores=[0.8, 0.81, 0.79], maximum_repeat_range=0.03,
    )
    passed = evaluate_stages_381_385(**args)
    assert passed["status"] == "PASS"
    assert passed["execution_authorized"] is False
    assert passed["proposal_only"] is True
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_381_385(**{**args, "observed_perturbations": ["noise"]})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
