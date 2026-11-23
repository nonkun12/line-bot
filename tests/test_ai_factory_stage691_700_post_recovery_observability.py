import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage691_700_post_recovery_observability.py"
s=importlib.util.spec_from_file_location("stage691",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def good():
 d={"readiness_gate_ref":"readiness","service_ref":"service",
 "observation_window":{"window_ref":"window","start_at":"2026-11-23T08:00:00Z","end_at":"2026-11-23T10:00:00Z","timezone_ref":"utc"},
 "telemetry_sources":[{"source_ref":"source","evidence_ref":"source-evidence","owner_ref":"owner","status":"PASS_DECLARED","live_collection_performed":False}],
 "coverage":[{"coverage_ref":"coverage","evidence_ref":"coverage-evidence","owner_ref":"owner","status":"PASS_DECLARED","live_collection_performed":False}],
 "alert_rules":[{"rule_ref":"rule","evidence_ref":"rule-evidence","owner_ref":"owner","status":"PASS_DECLARED","live_collection_performed":False}],
 "baseline":{"baseline_ref":"baseline","metric_definition_ref":"metric","evidence_ref":"baseline-evidence","owner_ref":"owner","status":"PASS_DECLARED","analysis_executed":False},
 "anomaly_review":{"review_ref":"anomaly","thresholds_ref":"thresholds","evidence_ref":"anomaly-evidence","owner_ref":"owner","status":"PASS_DECLARED","analysis_executed":False},
 "incident_recurrence":{"query_ref":"query","result_evidence_ref":"query-result","owner_ref":"owner","status":"PASS_DECLARED","analysis_executed":False},
 "postmortem":{"postmortem_ref":"postmortem","cause_analysis_ref":"cause","evidence_ref":"postmortem-evidence","owner_ref":"owner","status":"PASS_DECLARED","analysis_executed":False},
 "action_items":[{"action_ref":"action","owner_ref":"owner","due_date_ref":"due","acceptance_criteria_ref":"criteria","status":"OPEN_DECLARED","execution_performed":False}],
 "validation_plan":{"plan_ref":"plan","success_criteria_ref":"criteria","owner_ref":"owner","status":"PASS_DECLARED","analysis_executed":False},
 "independent_review":{"reviewer_ref":"reviewer","decision_ref":"decision","evidence_ref":"review-evidence","reviewed_at":"2026-11-23T10:05:00Z","decision":"ACCEPT_DECLARED","independent":True,"reviewer_authenticated":False},
 "audit_ref":"audit","created_at":"2026-11-23T10:10:00Z","auto_remediate":False}
 return d

def test_complete_is_review_only():
 r=m.stage_700_observability_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["telemetry_collected"] is False
 assert r["production_changes_authorized"] is False

def test_missing_or_non_object_blocks():
 x=good(); del x["baseline"]
 assert "baseline" in m.validate_post_recovery_observability(x)["missing"]
 assert m.validate_post_recovery_observability(None)["status"]=="BLOCKED"

def test_bad_window_blocks():
 x=good(); x["observation_window"]["end_at"]="2026-11-23T07:00:00Z"
 assert "observation_window_order_invalid" in m.validate_post_recovery_observability(x)["issues"]
 x=good(); x["observation_window"]["end_at"]="2026-11-24T07:00:00Z"
 assert "observation_window_after_record_creation" in m.validate_post_recovery_observability(x)["issues"]

def test_evidence_domains_fail_closed():
 for field in ("telemetry_sources","coverage","alert_rules"):
  x=good(); x[field][0]["status"]="UNKNOWN"
  assert field+"_not_pass_declared" in m.validate_post_recovery_observability(x)["issues"]
 for field in ("baseline","anomaly_review","incident_recurrence","postmortem","validation_plan"):
  x=good(); x[field]["status"]="FAIL_DECLARED"
  assert field+"_not_pass_declared" in m.validate_post_recovery_observability(x)["issues"]

def test_no_live_collection_or_analysis_claims():
 x=good(); x["telemetry_sources"][0]["live_collection_performed"]=True
 assert "telemetry_sources_live_collection_must_not_be_claimed" in m.validate_post_recovery_observability(x)["issues"]
 x=good(); x["baseline"]["analysis_executed"]=True
 assert "baseline_execution_must_not_be_claimed" in m.validate_post_recovery_observability(x)["issues"]
 x=good(); x["auto_remediate"]=True
 assert "automatic_remediation_must_be_false" in m.validate_post_recovery_observability(x)["issues"]

def test_action_items_require_owners_and_closure_evidence():
 x=good(); x["action_items"][0]["status"]="CLOSED_DECLARED"
 assert "closed_action_evidence_missing" in m.validate_post_recovery_observability(x)["issues"]
 x=good(); x["action_items"].append(dict(x["action_items"][0]))
 assert "action_refs_duplicate" in m.validate_post_recovery_observability(x)["issues"]

def test_independent_review_is_declaration_not_authentication():
 x=good(); x["independent_review"]["decision"]="PENDING"
 assert "independent_review_not_accepted" in m.validate_post_recovery_observability(x)["issues"]
 x=good(); x["independent_review"]["reviewer_authenticated"]=True
 assert "reviewer_authentication_must_not_be_claimed" in m.validate_post_recovery_observability(x)["issues"]
