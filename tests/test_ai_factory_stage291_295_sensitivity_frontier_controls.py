import hashlib

from core.ai_factory_stage291_295_sensitivity_frontier_controls import (
    stage291_test_threshold_sensitivity, stage292_detect_evaluator_drift,
    stage293_track_capability_frontier, stage294_compare_controlled_gain,
    stage295_integrate_research_readiness,
)


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sensitivity():
    return stage291_test_threshold_sensitivity(
        domain_deltas=[{"domain": "coding", "delta": 0.03, "evidence_digest": h("d1")},
                       {"domain": "math", "delta": -0.01, "evidence_digest": h("d2")}],
        regression_budgets=[0.01, 0.03, 0.05],
    )


def drift():
    return stage292_detect_evaluator_drift(calibration_rounds=[
        {"evaluator_id": "eval-a", "timestamp": i, "absolute_error": 0.10 + i * 0.01,
         "evidence_digest": h(f"cal-{i}")} for i in range(3)
    ])


def frontier():
    return stage293_track_capability_frontier(observations=[
        {"domain": "coding", "complexity_level": i, "score": 0.90 - i * 0.01,
         "evidence_digest": h(f"frontier-{i}")} for i in range(1, 4)
    ])


def control():
    return stage294_compare_controlled_gain(paired_observations=[
        {"pair_id": f"p{i}", "candidate_before": 0.50, "candidate_after": 0.60,
         "control_before": 0.50, "control_after": 0.52,
         "evidence_digest": h(f"pair-{i}")} for i in range(3)
    ])


def test_291_threshold_sensitivity_grid_and_fail_closed():
    assert sensitivity()["status"] == "SENSITIVITY_ROBUST"
    fragile = stage291_test_threshold_sensitivity(
        domain_deltas=[{"domain": "math", "delta": -0.20, "evidence_digest": h("bad")}],
        regression_budgets=[0.01, 0.02, 0.03])
    assert fragile["status"] == "SENSITIVITY_FRAGILE"
    assert stage291_test_threshold_sensitivity(
        domain_deltas=[], regression_budgets=[0.01, 0.01]
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_292_detects_evaluator_drift_and_requires_chronology():
    assert drift()["status"] == "EVALUATOR_DRIFT_WITHIN_LIMIT"
    rows = [{"evaluator_id": "e", "timestamp": i, "absolute_error": v,
             "evidence_digest": h(f"drift-{i}")} for i, v in enumerate([0.1, 0.3, 0.4])]
    assert stage292_detect_evaluator_drift(calibration_rounds=rows)["status"] == "EVALUATOR_DRIFT_DETECTED"
    rows[2]["timestamp"] = 1
    assert stage292_detect_evaluator_drift(calibration_rounds=rows)["status"] == "INSUFFICIENT_EVIDENCE"


def test_293_tracks_complexity_frontier_and_regression():
    assert frontier()["status"] == "CAPABILITY_FRONTIER_TRACKED"
    rows = [{"domain": "coding", "complexity_level": i, "score": s,
             "evidence_digest": h(f"reg-front-{i}")}
            for i, s in enumerate([0.9, 0.8, 0.7], 1)]
    assert stage293_track_capability_frontier(observations=rows)["status"] == "FRONTIER_REGRESSION_DETECTED"
    rows.append({"domain": "coding", "complexity_level": 3, "score": 0.7,
                 "evidence_digest": h("duplicate-level")})
    assert stage293_track_capability_frontier(observations=rows)["status"] == "INSUFFICIENT_EVIDENCE"


def test_294_requires_matched_pairs_and_positive_control_adjusted_gain():
    assert control()["status"] == "CONTROL_ADJUSTED_GAIN_PASSED"
    rows = [{"pair_id": f"p{i}", "candidate_before": 0.5, "candidate_after": 0.51,
             "control_before": 0.5, "control_after": 0.52,
             "evidence_digest": h(f"no-gain-{i}")} for i in range(3)]
    assert stage294_compare_controlled_gain(paired_observations=rows)["status"] == "CONTROL_ADJUSTED_GAIN_NOT_ESTABLISHED"
    assert stage294_compare_controlled_gain(paired_observations=rows[:2])["status"] == "INSUFFICIENT_EVIDENCE"


def test_295_integrates_only_all_sealed_positive_gates():
    result = stage295_integrate_research_readiness(
        sensitivity_result=sensitivity(), evaluator_drift_result=drift(),
        frontier_result=frontier(), control_result=control())
    assert result["status"] == "RESEARCH_READINESS_EVIDENCE_PASSED"
    assert result["asi_demonstrated"] is False
    tampered = {**frontier(), "domain_frontiers": []}
    assert stage295_integrate_research_readiness(
        sensitivity_result=sensitivity(), evaluator_drift_result=drift(),
        frontier_result=tampered, control_result=control()
    )["status"] == "INSUFFICIENT_EVIDENCE"
