import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage651",Path(__file__).parents[1]/"core/ai_factory_stage651_660_trust_drift_monitoring.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def good():
 return {
 "monitor_ref":"monitor-1","subject_ref":"subject-1","trust_evaluation_ref":"eval-1","policy_ref":"policy-1",
 "monitoring_window":{"start":"2026-11-23T10:00:00Z","end":"2026-11-23T11:00:00Z","coverage_declared_complete":True,"schedule_ref":"schedule-1"},
 "events":[{"event_ref":"event-1","source_ref":"source-1","observed_at":"2026-11-23T10:20:00Z","recorded_at":"2026-11-23T10:21:00Z","summary_ref":"summary-1","event_type":"POLICY_CHANGED","severity":"MEDIUM","status":"ACTIVE_DECLARED","source_authenticated":False}],
 "source_attestations":[{"source_ref":"source-1","provenance_ref":"provenance-1","captured_at":"2026-11-23T10:22:00Z","content_digest":"b"*64,"integrity_verified":False}],
 "impact_scope":{"resource_refs":["resource-1"],"claim_refs":["integrity"],"wildcard":False,"blast_radius":"SINGLE_SUBJECT"},
 "reassessment":{"due_at":"2026-11-23T12:00:00Z","owner_ref":"owner-1","procedure_ref":"procedure-1","required":True,"triggered_by_event_refs":["event-1"]},
 "containment":{"status":"RECOMMENDED","action_ref":"proposal-1","executed_by_system":False},
 "closure":{"status":"OPEN"},
 "audit_ref":"audit-1","automatic_action":False,"created_at":"2026-11-23T11:05:00Z"}

def test_complete_record_is_review_only():
 r=m.stage_660_trust_drift_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["live_monitoring_performed"] is False
 assert r["quarantine_executed"] is False

def test_missing_or_non_object_blocks():
 x=good(); del x["subject_ref"]
 assert "subject_ref" in m.validate_trust_drift_monitor(x)["missing"]
 assert m.validate_trust_drift_monitor([])["status"]=="BLOCKED"

def test_event_sequence_and_time_order_are_checked():
 x=good(); x["events"][0]["recorded_at"]="2026-11-23T10:00:00Z"
 assert "event_recorded_before_observed" in m.validate_trust_drift_monitor(x)["issues"]
 x=good(); x["events"].append({**x["events"][0],"event_ref":"event-2","observed_at":"2026-11-23T10:10:00Z"})
 assert "event_order_invalid" in m.validate_trust_drift_monitor(x)["issues"]

def test_sources_are_declared_and_digest_shaped():
 x=good(); x["events"][0]["source_ref"]="unknown"
 assert "event_source_not_declared" in m.validate_trust_drift_monitor(x)["issues"]
 x=good(); x["source_attestations"][0]["content_digest"]="invalid"
 assert "source_content_digest_invalid" in m.validate_trust_drift_monitor(x)["issues"]

def test_explicit_bounded_impact_required():
 x=good(); x["impact_scope"]["wildcard"]=True
 assert "impact_wildcard_must_be_false" in m.validate_trust_drift_monitor(x)["issues"]
 x=good(); x["impact_scope"]["blast_radius"]="GLOBAL"
 assert "impact_blast_radius_invalid" in m.validate_trust_drift_monitor(x)["issues"]

def test_reassessment_is_mandatory_and_references_known_events():
 x=good(); x["reassessment"]["required"]=False
 assert "reassessment_must_be_required" in m.validate_trust_drift_monitor(x)["issues"]
 x=good(); x["reassessment"]["triggered_by_event_refs"]=["missing"]
 assert "reassessment_unknown_event_ref" in m.validate_trust_drift_monitor(x)["issues"]

def test_containment_is_proposal_only():
 x=good(); x["containment"]["executed_by_system"]=True
 assert "automatic_containment_must_be_false" in m.validate_trust_drift_monitor(x)["issues"]
 x=good(); x["automatic_action"]=True
 assert "automatic_action_must_be_false" in m.validate_trust_drift_monitor(x)["issues"]

def test_closure_requires_evidence_and_no_active_events_when_resolved():
 x=good(); x["closure"]={"status":"RESOLVED_DECLARED","resolution_ref":"resolution-1"}
 assert "resolved_with_active_events" in m.validate_trust_drift_monitor(x)["issues"]
 x=good(); x["closure"]={"status":"DISMISSED_DECLARED"}
 assert "closure_resolution_ref_missing" in m.validate_trust_drift_monitor(x)["issues"]
