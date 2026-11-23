import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage671",Path(__file__).parents[1]/"core/ai_factory_stage671_680_recovery_validation.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def good():
 return {
 "recovery_ref":"recovery-1","incident_ref":"incident-1","subject_ref":"subject-1","recovery_policy_ref":"policy-1",
 "recovery_point":{"snapshot_ref":"snapshot-1","source_ref":"source-1","captured_at":"2026-11-23T09:00:00Z","restore_manifest_ref":"manifest-1","manifest_digest":"c"*64,"restore_test_executed":False},
 "objectives":{"rto_target_seconds":3600,"rpo_target_seconds":300,"measured_rto_seconds":1800,"measured_rpo_seconds":120,"measurement_source_ref":"measurement-1","measurements_verified":False},
 "dependencies":[{"dependency_ref":"db-1","owner_ref":"db-owner","readiness_evidence_ref":"db-ready","status":"PASS_DECLARED"}],
 "integrity_checks":[{"check_ref":"integrity-1","artifact_ref":"backup-1","expected_digest_ref":"digest-1","result_evidence_ref":"result-1","status":"PASS_DECLARED","bytes_verified":False}],
 "reconciliation":{"procedure_ref":"reconcile-1","result_evidence_ref":"reconcile-result","owner_ref":"data-owner","status":"PASS_DECLARED","data_mutated_by_validator":False},
 "service_checks":[{"check_ref":"service-1","procedure_ref":"health-plan","result_evidence_ref":"health-result","status":"PASS_DECLARED"}],
 "regression_checks":[{"check_ref":"regression-1","procedure_ref":"regression-plan","result_evidence_ref":"regression-result","status":"PASS_DECLARED"}],
 "fallback_plan":{"trigger_conditions_ref":"fallback-trigger","procedure_ref":"fallback-procedure","owner_ref":"fallback-owner","recovery_point_ref":"snapshot-1","executed":False},
 "independent_signoff":{"reviewer_ref":"reviewer-1","decision_ref":"signoff-1","evidence_ref":"review-evidence","decided_at":"2026-11-23T10:00:00Z","decision":"ACCEPT_DECLARED","independent":True,"reviewer_authenticated":False},
 "residual_risks":[{"risk_ref":"risk-1","description_ref":"risk-description","owner_ref":"risk-owner","disposition":"MITIGATION_PLANNED"}],
 "audit_ref":"audit-1","automatic_restore":False,"created_at":"2026-11-23T10:05:00Z"}

def test_complete_recovery_is_review_only():
 r=m.stage_680_recovery_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
 assert r["return_to_service_authorized"] is False
 assert r["restore_executed"] is False

def test_missing_and_non_object_block():
 x=good(); del x["recovery_policy_ref"]
 assert "recovery_policy_ref" in m.validate_recovery_record(x)["missing"]
 assert m.validate_recovery_record(None)["status"]=="BLOCKED"

def test_bad_manifest_digest_and_future_recovery_point_block():
 x=good(); x["recovery_point"]["manifest_digest"]="not-a-digest"
 assert "recovery_manifest_digest_invalid" in m.validate_recovery_record(x)["issues"]
 x=good(); x["recovery_point"]["captured_at"]="2026-11-24T09:00:00Z"
 assert "recovery_point_after_record_creation" in m.validate_recovery_record(x)["issues"]

def test_rto_rpo_targets_are_checked_but_not_verified():
 x=good(); x["objectives"]["measured_rto_seconds"]=7200
 assert "rto_target_exceeded_declared" in m.validate_recovery_record(x)["issues"]
 x=good(); x["objectives"]["measurements_verified"]=True
 assert "objective_measurement_verification_must_not_be_claimed" in m.validate_recovery_record(x)["issues"]

def test_dependency_and_integrity_records_fail_closed():
 x=good(); x["dependencies"][0]["status"]="UNKNOWNISH"
 assert "dependency_status_invalid" in m.validate_recovery_record(x)["issues"]
 x=good(); x["integrity_checks"][0]["bytes_verified"]=True
 assert "artifact_byte_verification_must_not_be_claimed" in m.validate_recovery_record(x)["issues"]

def test_reconciliation_and_service_regression_evidence_required():
 x=good(); x["reconciliation"]["status"]="FAIL_DECLARED"
 assert m.validate_recovery_record(x)["status"]=="DECLARATIONS_COMPLETE"
 x=good(); x["service_checks"]=[]
 assert "service_checks_invalid" in m.validate_recovery_record(x)["issues"]
 x=good(); x["regression_checks"][0]["result_evidence_ref"]=""
 assert "regression_checks_result_evidence_ref_invalid" in m.validate_recovery_record(x)["issues"]

def test_fallback_and_independent_signoff_are_declarations_only():
 x=good(); x["fallback_plan"]["executed"]=True
 assert "fallback_execution_must_not_be_claimed" in m.validate_recovery_record(x)["issues"]
 x=good(); x["independent_signoff"]["independent"]=False
 assert "independent_signoff_required" in m.validate_recovery_record(x)["issues"]

def test_residual_risks_and_no_automatic_restore():
 x=good(); x["residual_risks"][0]["disposition"]="IGNORED"
 assert "residual_risk_disposition_invalid" in m.validate_recovery_record(x)["issues"]
 x=good(); x["automatic_restore"]=True
 assert "automatic_restore_must_be_false" in m.validate_recovery_record(x)["issues"]
