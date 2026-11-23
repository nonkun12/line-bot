import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage661",Path(__file__).parents[1]/"core/ai_factory_stage661_670_incident_response_evidence.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def good():
 return {
 "incident_ref":"incident-1","subject_ref":"subject-1","trigger_event_refs":["event-1"],
 "classification":{"severity":"HIGH","status":"TRIAGED","rationale_ref":"classify-1","scope_confirmed":True},
 "timeline":[{"entry_ref":"timeline-1","event_ref":"event-1","occurred_at":"2026-11-23T10:00:00Z","recorded_at":"2026-11-23T10:01:00Z","description_ref":"desc-1"}],
 "decision_record":{"decision":"CONTAINMENT_RECOMMENDED","decision_ref":"decision-1","decision_owner_ref":"owner-1","rationale_ref":"why-1","authority_verified":False,"human_approval_required":True},
 "response_plan":[{"action_ref":"action-1","owner_ref":"owner-1","target_ref":"resource-1","rationale_ref":"reason-1","action_type":"ISOLATE_RESOURCE","execution_state":"PROPOSED","authorized":False}],
 "approvals":[{"approval_ref":"approval-1","approver_ref":"approver-1","action_ref":"action-1","action_owner_ref":"owner-1","decided_at":"2026-11-23T10:02:00Z","state":"PENDING","authority_verified":False}],
 "execution_records":[{"execution_ref":"execution-1","action_ref":"action-1","state":"NOT_STARTED","evidence_ref":"not-run-1"}],
 "rollback_plan":{"required":True,"trigger_conditions_ref":"trigger-1","procedure_ref":"rollback-1","recovery_point_ref":"snapshot-1","owner_ref":"rollback-owner","executed":False},
 "verification_plan":{"test_plan_ref":"tests-1","expected_result_ref":"expected-1","independent_verifier_ref":"verifier-1","independent":True,"verification_executed":False},
 "closure_record":{"status":"OPEN"},
 "audit_ref":"audit-1","automatic_execution":False,"created_at":"2026-11-23T10:05:00Z"}

def test_complete_incident_is_review_only():
 r=m.stage_670_incident_response_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["actions_executed"] is False
 assert r["containment_executed"] is False

def test_missing_and_malformed_fail_closed():
 x=good(); del x["incident_ref"]
 assert "incident_ref" in m.validate_incident_response(x)["missing"]
 assert m.validate_incident_response(None)["status"]=="BLOCKED"

def test_timeline_order_and_timestamp_integrity():
 x=good(); x["timeline"][0]["recorded_at"]="2026-11-23T09:00:00Z"
 assert "timeline_recorded_before_occurrence" in m.validate_incident_response(x)["issues"]
 x=good(); x["timeline"].append({**x["timeline"][0],"entry_ref":"t2","occurred_at":"2026-11-23T09:30:00Z"})
 assert "timeline_order_invalid" in m.validate_incident_response(x)["issues"]

def test_decision_requires_human_approval_and_no_authority_claim():
 x=good(); x["decision_record"]["human_approval_required"]=False
 assert "human_approval_requirement_missing" in m.validate_incident_response(x)["issues"]
 x=good(); x["decision_record"]["authority_verified"]=True
 assert "authority_verification_must_not_be_claimed" in m.validate_incident_response(x)["issues"]

def test_actions_require_evidence_if_execution_is_declared():
 x=good(); x["response_plan"][0]["execution_state"]="EXECUTED_DECLARED"
 assert "action_execution_evidence_missing" in m.validate_incident_response(x)["issues"]
 x=good(); x["response_plan"][0]["authorized"]=True
 assert "authorization_must_not_be_claimed" in m.validate_incident_response(x)["issues"]

def test_approval_separation_of_duties():
 x=good(); x["approvals"][0]["approver_ref"]="owner-1"
 assert "approver_must_differ_from_action_owner" in m.validate_incident_response(x)["issues"]

def test_rollback_and_independent_verification_are_required():
 x=good(); x["rollback_plan"]["executed"]=True
 assert "rollback_execution_must_be_false" in m.validate_incident_response(x)["issues"]
 x=good(); x["verification_plan"]["independent"]=False
 assert "independent_verification_required" in m.validate_incident_response(x)["issues"]

def test_closure_needs_independent_evidence_and_clean_actions():
 x=good(); x["closure_record"]={"status":"CLOSED_DECLARED","closure_evidence_ref":"close-1","verifier_ref":"v-1","lessons_ref":"lessons-1","independent_verification_passed":True}
 x["response_plan"][0]["execution_state"]="UNKNOWN"
 assert "closure_with_failed_or_unknown_action" in m.validate_incident_response(x)["issues"]
 x=good(); x["closure_record"]={"status":"CLOSED_DECLARED"}
 assert "closure_closure_evidence_ref_missing" in m.validate_incident_response(x)["issues"]

def test_automatic_execution_is_never_allowed():
 x=good(); x["automatic_execution"]=True
 assert "automatic_execution_must_be_false" in m.validate_incident_response(x)["issues"]
