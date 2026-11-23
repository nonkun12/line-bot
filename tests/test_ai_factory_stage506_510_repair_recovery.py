from core.ai_factory_stage506_510_repair_recovery import *
def test_506_failed_repair_requires_containment_evidence():
 r=[{"repair_id":"r","failure_reason":"err","evidence_ref":"e","rollback_status":"rolled_back","containment_ref":"c","containment_confirmed":True}]
 assert check_failed_repair_records(r)["pass"]
 assert not check_failed_repair_records([{**r[0],"containment_confirmed":False}])["pass"]
def test_507_recovery_plan_fail_closed():
 p={"recovery_steps_ref":"s","rollback_ref":"b","revalidation_ref":"v","owner_or_system_ref":"o","rollback_required":True,"restart_allowed":False}
 assert check_recovery_protocol(p)["pass"]
 assert not check_recovery_protocol({**p,"restart_allowed":True})["pass"]
def test_508_recurrence_monitoring_not_verified_claim():
 r=[{"failure_signature":"sig","observed_ref":"obs","window_id":"w"}]
 assert check_recurrence_monitoring(r,"window")["pass"]
 assert check_recurrence_monitoring(r,"")["recurrence_claim_verified"] is False
def test_509_prevention_is_proposal_only():
 a={"action_id":"a","scope":"test-only","evidence_ref":"e","test_ref":"t","rollback_ref":"b","applied":False,"review_required":True}
 assert check_preventive_action(a)["pass"]
 assert not check_preventive_action({**a,"applied":True})["pass"]
def test_510_hold_blocks_recovery_gate():
 r=evaluate_506_510(failed_repairs=[{"repair_id":"r","failure_reason":"e","evidence_ref":"f","rollback_status":"n/a","containment_ref":"c","containment_confirmed":True}],recovery_protocol={"recovery_steps_ref":"s","rollback_ref":"b","revalidation_ref":"v","owner_or_system_ref":"o","rollback_required":True,"restart_allowed":False},recurrence_records=[{"failure_signature":"sig","observed_ref":"obs","window_id":"w"}],recurrence_window="window",preventive_action={"action_id":"a","scope":"s","evidence_ref":"e","test_ref":"t","rollback_ref":"r","applied":False,"review_required":True},unresolved_holds=[{"id":"H"}])
 assert r["status"]=="HOLD" and r["rollback_executed"] is False
