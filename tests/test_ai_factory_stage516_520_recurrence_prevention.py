import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("recurrence", Path(__file__).parents[1] / "core/ai_factory_stage516_520_recurrence_prevention.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_prevention_check_fail_closed_and_safe():
    assert m.recurrence_prevention_check({})["status"] == "BLOCKED"
    ok={"cause_ref":"c","prevention_change_ref":"p","regression_test_ref":"r","monitoring_ref":"m","hold":True,"prevention_verified":True}
    assert m.recurrence_prevention_check(ok)["change_execution_allowed"] is False


def test_incident_refs_unique():
    assert m.compare_incidents([{"incident_ref":"a"},{"incident_ref":"b"}])["status"] == "DECLARATIONS_COMPLETE"
    assert m.compare_incidents([{"incident_ref":"a"},{"incident_ref":"a"}])["status"] == "BLOCKED"


def test_monitoring_and_claim_checks():
    good={"window_ref":"w","baseline_ref":"b","observation_ref":"o","window_closed":True,"hold":True}
    assert m.validate_monitoring_window(good)["promotion_allowed"] is False
    assert m.validate_claims({"claims":["recurrence_eliminated"]})["status"] == "BLOCKED"
    assert m.validate_claims({"claims":["review_only"]})["status"] == "DECLARATIONS_COMPLETE"


def test_integrated_gate_holds():
    rec={"cause_ref":"c","prevention_change_ref":"p","regression_test_ref":"r","monitoring_ref":"m","hold":True,"prevention_verified":True}
    inc=[{"incident_ref":"i1"},{"incident_ref":"i2"}]
    monitor={"window_ref":"w","baseline_ref":"b","observation_ref":"o","window_closed":True,"hold":True}
    result=m.recurrence_gate(rec,inc,monitor,{"claims":["review_only"]})
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["repair_or_promotion_authorized"] is False
