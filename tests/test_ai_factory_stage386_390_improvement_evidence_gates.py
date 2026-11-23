from core.ai_factory_stage386_390_improvement_evidence_gates import (
    check_benchmark_compatibility,
    check_guardrail_metrics,
    check_minimum_improvement,
    check_paired_sample_alignment,
    evaluate_stages_386_390,
)


def test_stage_386_requires_exact_unique_paired_sample_ids():
    baseline = [{"sample_id": "a"}, {"sample_id": "b"}]
    assert check_paired_sample_alignment(baseline, baseline)["pass"]
    result = check_paired_sample_alignment(
        [{"sample_id": "a"}, {"sample_id": "c"}], baseline
    )
    assert not result["pass"]
    assert result["missing_candidate_samples"] == ["b"]
    assert result["unexpected_candidate_samples"] == ["c"]


def test_stage_387_requires_minimum_mean_paired_improvement():
    assert check_minimum_improvement(
        [0.1, 0.2], minimum_mean_improvement=0.15
    )["pass"]
    result = check_minimum_improvement(
        [0.01, 0.02], minimum_mean_improvement=0.1
    )
    assert not result["pass"]
    assert "minimum_improvement_not_met" in result["errors"]
    assert "paired_delta_invalid" in check_minimum_improvement(
        [float("nan")], minimum_mean_improvement=0.0
    )["errors"]


def test_stage_388_blocks_guardrail_metric_degradation():
    assert check_guardrail_metrics([
        {"baseline": 0.8, "candidate": 0.79, "direction": "higher", "maximum_degradation": 0.02},
        {"baseline": 10, "candidate": 11, "direction": "lower", "maximum_degradation": 1},
    ])["pass"]
    result = check_guardrail_metrics([
        {"baseline": 0.8, "candidate": 0.7, "direction": "higher", "maximum_degradation": 0.05}
    ])
    assert not result["pass"]
    assert "guardrail_degradation_exceeded:0" in result["errors"]


def test_stage_389_requires_same_benchmark_protocol_and_metric_schema():
    identity = {"benchmark_id": "b1", "protocol_digest": "p1", "metric_schema_digest": "m1"}
    assert check_benchmark_compatibility(identity, identity)["pass"]
    result = check_benchmark_compatibility(identity, {**identity, "protocol_digest": "p2"})
    assert not result["pass"]
    assert "benchmark_identity_mismatch:protocol_digest" in result["errors"]


def test_stage_390_integrates_improvement_gate_without_authorizing_promotion():
    identity = {"benchmark_id": "b1", "protocol_digest": "p1", "metric_schema_digest": "m1"}
    args = dict(
        candidate_samples=[{"sample_id": "a"}, {"sample_id": "b"}],
        baseline_samples=[{"sample_id": "a"}, {"sample_id": "b"}],
        paired_improvements=[0.1, 0.2], minimum_mean_improvement=0.1,
        guardrail_metrics=[{"baseline": 0.8, "candidate": 0.79,
                            "direction": "higher", "maximum_degradation": 0.02}],
        candidate_benchmark=identity, baseline_benchmark=identity,
    )
    passed = evaluate_stages_386_390(**args)
    assert passed["status"] == "PASS"
    assert passed["execution_authorized"] is False
    assert passed["promotion_authorized"] is False
    assert passed["proposal_only"] is True
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_386_390(**{**args, "paired_improvements": [0.0, 0.01]})
    assert blocked["status"] == "BLOCKED"
    assert blocked["promotion_authorized"] is False
