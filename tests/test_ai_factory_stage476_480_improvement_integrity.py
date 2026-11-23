from core.ai_factory_stage476_480_improvement_integrity import (
    check_cycle_completion, check_evidence_traceability, check_protocol_stability,
    check_score_contract, evaluate_stages_476_480,
)


def cycles():
    return [
        {"cycle_id": "c1", "sequence": 1, "baseline_ref": "b1", "candidate_ref": "n1",
         "evaluation_ref": "e1", "protocol_id": "p", "protocol_version": "1",
         "task_set_id": "tasks", "metric_id": "accuracy", "scoring_method": "ratio",
         "state": "complete", "artifact_ref": "a1", "report_ref": "r1", "evidence_sha256": "a" * 64},
        {"cycle_id": "c2", "sequence": 2, "baseline_ref": "b2", "candidate_ref": "n2",
         "evaluation_ref": "e2", "protocol_id": "p", "protocol_version": "1",
         "task_set_id": "tasks", "metric_id": "accuracy", "scoring_method": "ratio",
         "state": "complete", "artifact_ref": "a2", "report_ref": "r2", "evidence_sha256": "b" * 64},
    ]


def test_476_rejects_protocol_drift():
    assert check_protocol_stability(cycles())["pass"]
    changed = cycles()
    changed[1]["protocol_version"] = "2"
    assert not check_protocol_stability(changed)["pass"]


def test_477_enforces_score_bounds_and_direction():
    rows = [{"metric_id": "accuracy", "score": 0.8, "direction": "higher_is_better"}]
    assert check_score_contract(rows, minimum_score=0, maximum_score=1,
                                direction="higher_is_better")["pass"]
    assert not check_score_contract([{**rows[0], "score": 1.1}], minimum_score=0,
                                    maximum_score=1, direction="higher_is_better")["pass"]


def test_478_rejects_incomplete_cycle_states():
    assert check_cycle_completion(cycles(), required_states=["complete"])["pass"]
    changed = cycles()
    changed[0]["state"] = "interrupted"
    assert not check_cycle_completion(changed, required_states=["complete"])["pass"]


def test_479_requires_unique_references_and_digest_shape():
    assert check_evidence_traceability(cycles(),
        required_evidence_fields=["artifact_ref", "report_ref"])["pass"]
    changed = cycles()
    changed[1]["artifact_ref"] = changed[0]["artifact_ref"]
    assert not check_evidence_traceability(changed,
        required_evidence_fields=["artifact_ref", "report_ref"])["pass"]


def test_480_integrated_gate_holds_on_any_open_hold_and_never_authorizes():
    result = evaluate_stages_476_480(
        cycles=cycles(), expected_cycles=2, cycle_scores=[0.8, 0.82],
        minimum_cycles=2, minimum_score=0.8, required_consecutive_passes=2,
        maximum_drop=0.05, trend_window_size=2,
        evaluator_results=[{"evaluator_id": "e1", "score": 0.8},
                           {"evaluator_id": "e2", "score": 0.82}],
        minimum_evaluators=2, maximum_evaluator_spread=0.05,
        score_records=[{"metric_id": "accuracy", "score": 0.82,
                        "direction": "higher_is_better"}],
        score_minimum=0, score_maximum=1, direction="higher_is_better",
        required_states=["complete"], required_evidence_fields=["artifact_ref", "report_ref"],
        unresolved_holds=[])
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["improvement_verified"] is False
    assert result["evidence_authenticity_verified"] is False
    assert result["hold_release_authorized"] is False
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert result["merge_authorized"] is False
    assert result["deployment_authorized"] is False
    blocked = evaluate_stages_476_480(
        cycles=cycles(), expected_cycles=2, cycle_scores=[0.8, 0.82],
        minimum_cycles=2, minimum_score=0.8, required_consecutive_passes=2,
        maximum_drop=0.05, trend_window_size=2,
        evaluator_results=[{"evaluator_id": "e1", "score": 0.8},
                           {"evaluator_id": "e2", "score": 0.82}],
        minimum_evaluators=2, maximum_evaluator_spread=0.05,
        score_records=[{"metric_id": "accuracy", "score": 0.82,
                        "direction": "higher_is_better"}],
        score_minimum=0, score_maximum=1, direction="higher_is_better",
        required_states=["complete"], required_evidence_fields=["artifact_ref", "report_ref"],
        unresolved_holds=[{"hold_id": "h1", "reason": "pending", "required_evidence": "report"}])
    assert blocked["status"] == "HOLD"
