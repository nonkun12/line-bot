import hashlib

from core.ai_factory_stage286_290_longitudinal_robustness_gates import (
    stage286_measure_longitudinal_stability, stage287_enforce_regression_budget,
    stage288_check_consensus_robustness, stage289_enforce_holdout_separation,
    stage290_integrate_robustness_gate,
)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def stability():
    return stage286_measure_longitudinal_stability(rounds=[
        {"round_id": f"r{i}", "timestamp": i, "domain": "coding",
         "score": 0.80 + i * 0.01, "evidence_digest": h(f"round-{i}")}
        for i in range(3)
    ])


def regression():
    return stage287_enforce_regression_budget(domain_deltas=[
        {"domain": "coding", "delta": 0.02, "evidence_digest": h("delta")}
    ])


def consensus():
    return stage288_check_consensus_robustness(evaluator_scores=[
        {"domain": "coding", "evaluator_id": f"e{i}", "score": 0.80 + i * 0.01,
         "evidence_digest": h(f"eval-{i}")}
        for i in range(3)
    ])


def holdout():
    return stage289_enforce_holdout_separation(
        development_task_digests=[h(f"dev-{i}") for i in range(3)],
        holdout_task_digests=[h(f"hold-{i}") for i in range(10)],
    )


def test_286_checks_chronology_and_per_domain_stability():
    assert stability()["status"] == "LONGITUDINAL_STABILITY_PASSED"
    rows = [{"round_id": f"r{i}", "timestamp": i, "domain": "coding",
             "score": [0.1, 0.8, 0.2][i], "evidence_digest": h(f"x{i}")}
            for i in range(3)]
    assert stage286_measure_longitudinal_stability(rounds=rows)["status"] == "LONGITUDINAL_INSTABILITY_DETECTED"
    rows[2]["timestamp"] = 1
    assert stage286_measure_longitudinal_stability(rounds=rows)["status"] == "INSUFFICIENT_EVIDENCE"


def test_287_fails_on_any_domain_regression_over_budget():
    assert regression()["status"] == "REGRESSION_BUDGET_PASSED"
    result = stage287_enforce_regression_budget(domain_deltas=[
        {"domain": "coding", "delta": 0.01, "evidence_digest": h("a")},
        {"domain": "math", "delta": -0.10, "evidence_digest": h("b")},
    ])
    assert result["status"] == "REGRESSION_BUDGET_EXCEEDED"
    assert result["regressed_domains"] == ["math"]


def test_288_uses_median_absolute_deviation_and_minimum_evaluators():
    assert consensus()["status"] == "EVALUATOR_CONSENSUS_ROBUST"
    rows = [{"domain": "coding", "evaluator_id": f"e{i}", "score": v,
             "evidence_digest": h(f"outlier-{i}")}
            for i, v in enumerate([0.1, 0.5, 0.9])]
    assert stage288_check_consensus_robustness(evaluator_scores=rows)["status"] == "EVALUATOR_DISAGREEMENT"


def test_289_rejects_overlap_and_insufficient_holdout():
    assert holdout()["status"] == "HOLDOUT_SEPARATION_PASSED"
    shared = h("shared")
    assert stage289_enforce_holdout_separation(
        development_task_digests=[shared],
        holdout_task_digests=[shared] + [h(f"h{i}") for i in range(9)],
    )["status"] == "HOLDOUT_CONTAMINATION_DETECTED"
    assert stage289_enforce_holdout_separation(
        development_task_digests=[h("d")], holdout_task_digests=[h("h")]
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_290_requires_all_sealed_robustness_gates():
    result = stage290_integrate_robustness_gate(
        stability_result=stability(), regression_result=regression(),
        consensus_result=consensus(), holdout_result=holdout(),
    )
    assert result["status"] == "ROBUSTNESS_EVIDENCE_INTEGRATED"
    assert result["rsi_or_asi_demonstrated"] is False
    tampered = {**stability(), "domain_stability": []}
    assert stage290_integrate_robustness_gate(
        stability_result=tampered, regression_result=regression(),
        consensus_result=consensus(), holdout_result=holdout(),
    )["status"] == "INSUFFICIENT_EVIDENCE"
