import hashlib
import json

from core.ai_factory_stage421_425_evaluation_audit_trails import (
    check_actor_role_separation, check_event_identity, check_event_order,
    check_record_integrity, evaluate_stages_421_425,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def test_421_event_identity_and_sequence_uniqueness():
    assert check_event_identity([{"event_id": "e1", "run_id": "r1", "sequence": 1}])["pass"]
    assert not check_event_identity([
        {"event_id": "e1", "run_id": "r1", "sequence": 1},
        {"event_id": "e1", "run_id": "r1", "sequence": 1},
    ])["pass"]


def test_422_requires_contiguous_event_order():
    assert check_event_order([
        {"run_id": "r1", "sequence": 1}, {"run_id": "r1", "sequence": 2}
    ])["pass"]
    assert not check_event_order([
        {"run_id": "r1", "sequence": 1}, {"run_id": "r1", "sequence": 3}
    ])["pass"]


def test_423_recomputes_canonical_record_digest():
    payload = {"decision": "BLOCKED", "reason": "missing evidence"}
    assert check_record_integrity([{"record_id": "d1", "payload": payload,
                                    "sha256": digest(payload)}])["pass"]
    assert not check_record_integrity([{"record_id": "d1", "payload": payload,
                                        "sha256": "0" * 64}])["pass"]


def test_424_rejects_same_declared_generator_and_evaluator():
    assert check_actor_role_separation([{"assessment_id": "a1",
                                         "generator_actor": "agent-a",
                                         "evaluator_actor": "agent-b"}])["pass"]
    assert not check_actor_role_separation([{"assessment_id": "a1",
                                              "generator_actor": "agent-a",
                                              "evaluator_actor": "agent-a"}])["pass"]


def test_425_fail_closed_and_never_grants_authority():
    args = {
        "events": [{"event_id": "e1", "run_id": "r1", "sequence": 1}],
        "records": [{"record_id": "d1", "payload": {"status": "PASS"},
                     "sha256": digest({"status": "PASS"})}],
        "actor_assignments": [{"assessment_id": "a1",
                               "generator_actor": "agent-a",
                               "evaluator_actor": "agent-b"}],
    }
    result = evaluate_stages_421_425(**args)
    assert result["status"] == "PASS"
    assert result["execution_authorized"] is False
    assert result["promotion_authorized"] is False
    assert len(result["seal"]) == 64
    blocked = evaluate_stages_421_425(**{**args, "events": []})
    assert blocked["status"] == "BLOCKED"
    assert blocked["execution_authorized"] is False
