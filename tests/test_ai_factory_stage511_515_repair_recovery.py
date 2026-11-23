import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("recovery", Path(__file__).parents[1] / "core/ai_factory_stage511_515_repair_recovery.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def good():
    return {"incident_id":"i1","repair_ref":"r1","failure_ref":"f1","impact_scope":"test-only",
            "recovery_plan_ref":"rp","rollback_ref":"rb","verification_ref":"v",
            "recovery_status":"verified","hold":True}


def test_recovery_record_fail_closed():
    assert m.validate_recovery_record({})["status"] == "BLOCKED"
    assert m.validate_recovery_record(good())["execution_allowed"] is False


def test_recovery_attempts_need_two_unique_refs():
    assert m.compare_recovery_attempts([])["status"] == "BLOCKED"
    assert m.compare_recovery_attempts([{"attempt_id":"1","evidence_ref":"e1"},{"attempt_id":"2","evidence_ref":"e2"}])["status"] == "DECLARATIONS_COMPLETE"
    assert m.compare_recovery_attempts([{"attempt_id":"1","evidence_ref":"e1"},{"attempt_id":"1","evidence_ref":"e1"}])["status"] == "BLOCKED"


def test_boundary_and_test_gate():
    assert m.validate_recovery_boundary({"automatic_retry":True})["status"] == "BLOCKED"
    assert m.validate_post_recovery_tests({"test_ref":"t","regression_ref":"g","independent_check_ref":"i","tests_pass":True,"hold":True})["merge_or_deploy_authorized"] is False


def test_final_gate_does_not_authorize_recovery():
    result = m.recovery_review_gate([good()])
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["recovery_execution_authorized"] is False
