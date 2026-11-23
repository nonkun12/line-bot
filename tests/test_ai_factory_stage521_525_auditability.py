import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("audit",Path(__file__).parents[1]/"core/ai_factory_stage521_525_auditability.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good_event():
 return {"event_id":"e1","event_type":"review","actor_ref":"actor","target_ref":"task","timestamp":"2026-01-01T00:00Z","evidence_ref":"ev","hold":True}

def test_event_validation():
 assert m.audit_event_check({})["status"]=="BLOCKED"
 assert m.audit_event_check(good_event())["actions_authorized"] is False

def test_chain_requires_unique_ids_and_refs():
 assert m.audit_chain_check([])["status"]=="BLOCKED"
 assert m.audit_chain_check([good_event(),dict(good_event(),event_id="e2",evidence_ref="ev2")])["status"]=="DECLARATIONS_COMPLETE"
 assert m.audit_chain_check([good_event(),good_event()])["status"]=="BLOCKED"

def test_retention_and_access_fail_closed():
 assert m.validate_audit_retention({})["status"]=="BLOCKED"
 assert m.validate_audit_access({})["permission_changes_allowed"] is False

def test_integrated_gate_keeps_mutations_disabled():
 event=good_event(); events=[event]
 retention={"retention_policy_ref":"p","archive_ref":"a","access_control_ref":"c","retention_declared":True}
 access={"access_review_ref":"ar","reviewer_ref":"r","review_complete":True,"hold":True}
 result=m.audit_gate(event,events,retention,access)
 assert result["status"]=="READY_FOR_REVIEW"
 assert result["mutations_authorized"] is False
