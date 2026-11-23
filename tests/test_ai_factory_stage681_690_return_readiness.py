import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage681_690_return_readiness.py"
s=importlib.util.spec_from_file_location("stage681",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def good():
 d={"recovery_gate_ref":"recovery-gate","service_ref":"svc","policy_ref":"policy",
 "activation_plan_ref":"activation-plan","rollout_plan_ref":"rollout-plan",
 "canary_evidence_ref":"canary","slo_evidence_ref":"slo","capacity_evidence_ref":"capacity",
 "security_evidence_ref":"security","backup_evidence_ref":"backup","alerting_evidence_ref":"alerts",
 "handoff_ref":"handoff","audit_ref":"audit","created_at":"2026-11-23T12:00:00Z",
 "activation_executed":False,"traffic_shift_executed":False,"rollback_executed":False,
 "readiness_checks":[{"check_ref":"check-1","scope_ref":"scope","evidence_ref":"evidence","owner_ref":"owner","status":"PASS_DECLARED","live_probe_executed":False}]}
 for k in ("rollout","canary","slo","capacity","security","backup","alerting","handoff"):
  d[k]={"plan_ref":k+"-plan","evidence_ref":k+"-evidence","owner_ref":k+"-owner","status":"PASS_DECLARED"}
 return d

def test_complete_is_review_only():
 r=m.stage_690_return_readiness_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["return_to_service_authorized"] is False
 assert r["traffic_shift_performed"] is False

def test_missing_or_non_object_blocks():
 x=good(); del x["security_evidence_ref"]
 assert "security_evidence_ref" in m.validate_return_readiness(x)["missing"]
 assert m.validate_return_readiness([])["status"]=="BLOCKED"

def test_unknown_failed_or_duplicate_readiness_blocks():
 x=good(); x["readiness_checks"][0]["status"]="UNKNOWN"
 assert "readiness_check_not_pass_declared" in m.validate_return_readiness(x)["issues"]
 x=good(); x["readiness_checks"].append(dict(x["readiness_checks"][0]))
 assert "readiness_check_refs_duplicate" in m.validate_return_readiness(x)["issues"]

def test_execution_claims_are_rejected():
 for key in ("activation_executed","traffic_shift_executed","rollback_executed"):
  x=good(); x[key]=True
  assert m.validate_return_readiness(x)["status"]=="BLOCKED"
 x=good(); x["readiness_checks"][0]["live_probe_executed"]=True
 assert "live_probe_execution_must_not_be_claimed" in m.validate_return_readiness(x)["issues"]

def test_each_readiness_domain_must_pass_declared():
 for key in ("rollout","canary","slo","capacity","security","backup","alerting","handoff"):
  x=good(); x[key]["status"]="FAIL_DECLARED"
  assert key+"_not_pass_declared" in m.validate_return_readiness(x)["issues"]

def test_timestamp_and_evidence_shape():
 x=good(); x["created_at"]="not-a-date"
 assert "created_at_invalid" in m.validate_return_readiness(x)["issues"]
 x=good(); x["canary"]["evidence_ref"]=""
 assert "canary_evidence_ref_invalid" in m.validate_return_readiness(x)["issues"]
