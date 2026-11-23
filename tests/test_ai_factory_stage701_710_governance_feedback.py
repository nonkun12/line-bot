import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage701_710_governance_feedback.py"
s=importlib.util.spec_from_file_location("stage701",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def good():
 return {"observability_gate_ref":"obs-gate","scope_ref":"scope","policy_snapshot_ref":"policy-snapshot",
 "change_proposal":{"proposal_ref":"proposal","rationale_ref":"rationale","target_policy_ref":"target-policy","diff_ref":"diff","owner_ref":"owner","status":"PROPOSED","applied":False},
 "impact_assessment":{"assessment_ref":"impact","affected_scope_ref":"scope","evidence_ref":"impact-evidence","owner_ref":"owner","status":"PASS_DECLARED","assessment_executed":False},
 "risk_assessment":{"assessment_ref":"risk","threat_model_ref":"threat-model","evidence_ref":"risk-evidence","owner_ref":"owner","status":"PASS_DECLARED","unmitigated_critical":False,"assessment_executed":False},
 "approval_record":{"approval_ref":"approval","approver_ref":"approver","decision_evidence_ref":"approval-evidence","decided_at":"2026-11-23T10:00:00Z","decision":"APPROVE_DECLARED","approver_authenticated":False,"authorization_granted":False},
 "rollout_constraints":{"plan_ref":"constraints","evidence_ref":"constraints-evidence","owner_ref":"owner","status":"PASS_DECLARED","executed":False,"max_scope_ref":"bounded-scope"},
 "verification_plan":{"plan_ref":"verification","evidence_ref":"verification-evidence","owner_ref":"owner","status":"PASS_DECLARED","executed":False},
 "rollback_plan":{"plan_ref":"rollback","evidence_ref":"rollback-evidence","owner_ref":"owner","status":"PASS_DECLARED","executed":False},
 "decision_log":[{"decision_ref":"decision-1","basis_ref":"basis","owner_ref":"owner","recorded_at":"2026-11-23T10:05:00Z","outcome":"DEFERRED"}],
 "audit_ref":"audit","created_at":"2026-11-23T10:10:00Z","policy_mutation_executed":False}

def test_complete_is_review_only():
 r=m.stage_710_governance_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["policy_changed"] is False
 assert r["production_change_authorized"] is False

def test_missing_and_invalid_record_block():
 x=good(); del x["policy_snapshot_ref"]
 assert "policy_snapshot_ref" in m.validate_governance_feedback(x)["missing"]
 assert m.validate_governance_feedback(None)["status"]=="BLOCKED"

def test_policy_or_plan_execution_claims_block():
 x=good(); x["policy_mutation_executed"]=True
 assert "policy_mutation_must_not_be_claimed" in m.validate_governance_feedback(x)["issues"]
 x=good(); x["verification_plan"]["executed"]=True
 assert "verification_plan_execution_must_not_be_claimed" in m.validate_governance_feedback(x)["issues"]

def test_risk_and_impact_must_pass_declared():
 x=good(); x["risk_assessment"]["unmitigated_critical"]=True
 assert "unmitigated_critical_risk" in m.validate_governance_feedback(x)["issues"]
 x=good(); x["impact_assessment"]["status"]="UNKNOWN"
 assert "impact_assessment_not_pass_declared" in m.validate_governance_feedback(x)["issues"]

def test_approval_is_not_authorization_or_identity_proof():
 x=good(); x["approval_record"]["decision"]="PENDING"
 assert "approval_not_approved" in m.validate_governance_feedback(x)["issues"]
 x=good(); x["approval_record"]["authorization_granted"]=True
 assert "authorization_grant_must_not_be_claimed" in m.validate_governance_feedback(x)["issues"]
 x=good(); x["approval_record"]["approver_authenticated"]=True
 assert "approver_authentication_must_not_be_claimed" in m.validate_governance_feedback(x)["issues"]

def test_rollout_constraints_are_bounded_and_not_executed():
 x=good(); x["rollout_constraints"]["max_scope_ref"]=None
 assert "rollout_max_scope_ref_missing" in m.validate_governance_feedback(x)["issues"]
 x=good(); x["rollback_plan"]["executed"]=True
 assert "rollback_plan_execution_must_not_be_claimed" in m.validate_governance_feedback(x)["issues"]

def test_decision_log_requires_unique_references_and_valid_outcomes():
 x=good(); x["decision_log"].append(dict(x["decision_log"][0]))
 assert "decision_refs_duplicate" in m.validate_governance_feedback(x)["issues"]
 x=good(); x["decision_log"][0]["outcome"]="AUTO_APPLIED"
 assert "decision_outcome_invalid" in m.validate_governance_feedback(x)["issues"]
