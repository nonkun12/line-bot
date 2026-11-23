from core.ai_factory_stage396_400_final_evidence_readiness import (
    check_evidence_decision_consistency, check_evidence_time_windows,
    check_evaluator_separation, check_source_provenance_declarations,
    evaluate_stages_396_400,
)


def test_stage_396_requires_unique_source_and_version_declarations():
    assert check_source_provenance_declarations([
        {"evidence_id": "e1", "source_ref": "dataset://one", "source_version": "v1"}
    ])["pass"]
    result = check_source_provenance_declarations([
        {"evidence_id": "e1", "source_ref": "", "source_version": "v1"},
        {"evidence_id": "e1", "source_ref": "dataset://two", "source_version": ""},
    ])
    assert not result["pass"]
    assert "evidence_id_duplicate:e1" in result["errors"]
    assert "source_ref_missing:0" in result["errors"]


def test_stage_397_rejects_future_stale_and_reversed_time_windows():
    assert check_evidence_time_windows(
        [{"started_at": 90, "completed_at": 95}],
        maximum_age_seconds=10, evaluation_time=100)["pass"]
    result = check_evidence_time_windows(
        [{"started_at": 20, "completed_at": 10},
         {"started_at": 90, "completed_at": 110},
         {"started_at": 1, "completed_at": 2}],
        maximum_age_seconds=10, evaluation_time=100)
    assert not result["pass"]
    assert "time_order_invalid:0" in result["errors"]
    assert "future_timestamp:1" in result["errors"]
    assert "evidence_stale:2" in result["errors"]


def test_stage_398_requires_declared_evaluator_distinct_from_producer():
    assert check_evaluator_separation([
        {"artifact_id": "a1", "producer_id": "agent-a", "evaluator_id": "agent-b"}
    ])["pass"]
    result = check_evaluator_separation([
        {"artifact_id": "a1", "producer_id": "agent-a", "evaluator_id": "agent-a"}
    ])
    assert not result["pass"]
    assert "evaluator_not_distinct:a1" in result["errors"]


def test_stage_399_rejects_conflicting_decisions_for_same_evidence():
    assert check_evidence_decision_consistency([
        {"evidence_key": "e1", "decision": "PASS"},
        {"evidence_key": "e1", "decision": "PASS"},
    ])["pass"]
    result = check_evidence_decision_consistency([
        {"evidence_key": "e1", "decision": "PASS"},
        {"evidence_key": "e1", "decision": "FAIL"},
    ])
    assert not result["pass"]
    assert "conflicting_decision:e1" in result["errors"]


def test_stage_400_requires_all_upstream_gates_and_never_grants_authority():
    upstream = [{"stage": n, "status": "PASS", "seal": f"{n:064x}"}
                for n in range(386, 396)]
    args = dict(
        provenance_records=[{"evidence_id": "e1", "source_ref": "dataset://one",
                             "source_version": "v1"}],
        time_records=[{"started_at": 90, "completed_at": 95}],
        maximum_age_seconds=10, evaluation_time=100,
        evaluations=[{"artifact_id": "a1", "producer_id": "agent-a",
                      "evaluator_id": "agent-b"}],
        decisions=[{"evidence_key": "e1", "decision": "PASS"}],
        upstream_gates=upstream,
    )
    passed = evaluate_stages_396_400(**args)
    assert passed["status"] == "PASS"
    assert passed["proposal_only"] is True
    assert passed["execution_authorized"] is False
    assert passed["promotion_authorized"] is False
    assert len(passed["seal"]) == 64
    blocked = evaluate_stages_396_400(**{**args, "upstream_gates": upstream[:-1]})
    assert blocked["status"] == "BLOCKED"
    assert "upstream_stage_missing:395" in blocked["upstream_errors"]
    assert blocked["execution_authorized"] is False
    assert blocked["promotion_authorized"] is False
