import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage681",Path(__file__).parents[1]/"core/ai_factory_stage681_690_post_recovery_assurance.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def good():
 return {
 "assurance_ref":"assurance-1","recovery_ref":"recovery-1","subject_ref":"subject-1",
 "assurance_window":{"start":"2026-11-23T10:00:00Z","end":"2026-11-23T11:00:00Z","coverage_declared_complete":True,"schedule_ref":"schedule-1"},
 "service_observations":[{"observation_ref":"obs-1","service_ref":"api","observed_at":"2026-11-23T10:30:00Z","evidence_ref":"obs-evidence","observer_ref":"observer","status":"PASS_DECLARED","probe_executed_by_validator":False}],
 "slo_results":[{"slo_ref":"availability","metric_ref":"uptime","target":99.9,"observed_value":99.95,"unit":"percent","evidence_ref":"slo-evidence","comparison":"AT_LEAST","status":"PASS_DECLARED","measurement_verified":False}],
 "monitoring_coverage":{"required_signal_refs":["latency","errors"],"observed_signal_refs":["latency","errors"],"gap_refs":[],"coverage_verified":False},
 "recurrence_checks":[{"check_ref":"recurrence-1","failure_mode_ref":"failure-mode","procedure_ref":"recheck","evidence_ref":"recurrence-evidence","status":"PASS_DECLARED"}],
 "change_control":{"freeze_status":"ACTIVE_DECLARED","policy_ref":"change-policy","exception_register_ref":"exceptions","unapproved_changes_present":False,"enforced_by_validator":False},
 "rollback_readiness":{"plan_ref":"rollback-plan","recovery_point_ref":"recovery-point","owner_ref":"rollback-owner","readiness_evidence_ref":"rollback-ready","status":"PASS_DECLARED","rollback_executed":False},
 "impact_review":{"customer_impact_ref":"customer-impact","support_signal_ref":"support","reviewer_ref":"reviewer","status":"PASS_DECLARED","reviewer_authenticated":False},
 "followup_actions":[{"action_ref":"followup-1","owner_ref":"owner","due_at":"2026-11-24T12:00:00Z","tracking_ref":"ticket-1","status":"OPEN"}],
 "handover":{"receiving_owner_ref":"ops-owner","runbook_ref":"runbook","known_issues_ref":"known-issues","handover_evidence_ref":"handover","accepted_declared":True,"recipient_authenticated":False},
 "audit_ref":"audit-1","automatic_enforcement":False,"created_at":"2026-11-23T11:05:00Z"}

def test_complete_record_is_review_only():
 r=m.stage_690_post_recovery_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["production_stability_certified"] is False
 assert r["live_monitoring_performed"] is False

def test_missing_or_non_object_blocks():
 x=good(); del x["recovery_ref"]
 assert "recovery_ref" in m.validate_post_recovery_assurance(x)["missing"]
 assert m.validate_post_recovery_assurance(None)["status"]=="BLOCKED"

def test_window_and_observation_records_are_bounded():
 x=good(); x["assurance_window"]["coverage_declared_complete"]=False
 assert "assurance_window_incomplete" in m.validate_post_recovery_assurance(x)["issues"]
 x=good(); x["service_observations"][0]["probe_executed_by_validator"]=True
 assert "validator_probe_must_not_be_claimed" in m.validate_post_recovery_assurance(x)["issues"]

def test_slo_numeric_values_must_be_finite_and_verified_status_is_not_claimed():
 x=good(); x["slo_results"][0]["observed_value"]=float("nan")
 assert "slo_observed_value_invalid" in m.validate_post_recovery_assurance(x)["issues"]
 x=good(); x["slo_results"][0]["measurement_verified"]=True
 assert "slo_measurement_verification_must_not_be_claimed" in m.validate_post_recovery_assurance(x)["issues"]

def test_monitoring_gaps_block():
 x=good(); x["monitoring_coverage"]["gap_refs"]=["gap-1"]
 assert "monitoring_gaps_present" in m.validate_post_recovery_assurance(x)["issues"]
 x=good(); x["monitoring_coverage"]["observed_signal_refs"]=[]
 assert "monitoring_required_signals_missing" in m.validate_post_recovery_assurance(x)["issues"]

def test_recurrence_checks_must_pass():
 x=good(); x["recurrence_checks"][0]["status"]="UNKNOWN"
 assert "recurrence_not_pass_declared" in m.validate_post_recovery_assurance(x)["issues"]

def test_change_control_and_rollback_must_be_ready():
 x=good(); x["change_control"]["unapproved_changes_present"]=True
 assert "unapproved_changes_must_be_absent" in m.validate_post_recovery_assurance(x)["issues"]
 x=good(); x["rollback_readiness"]["status"]="FAIL_DECLARED"
 assert "rollback_not_pass_declared" in m.validate_post_recovery_assurance(x)["issues"]

def test_impact_handover_and_followup_evidence_required():
 x=good(); x["impact_review"]["status"]="FAIL_DECLARED"
 assert "impact_review_not_pass_declared" in m.validate_post_recovery_assurance(x)["issues"]
 x=good(); x["handover"]["accepted_declared"]=False
 assert "handover_not_accepted_declared" in m.validate_post_recovery_assurance(x)["issues"]
 x=good(); x["followup_actions"][0]["status"]="COMPLETED_DECLARED"
 assert "followup_completion_evidence_missing" in m.validate_post_recovery_assurance(x)["issues"]

def test_automatic_enforcement_is_prohibited():
 x=good(); x["automatic_enforcement"]=True
 assert "automatic_enforcement_must_be_false" in m.validate_post_recovery_assurance(x)["issues"]
