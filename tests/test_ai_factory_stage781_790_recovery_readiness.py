import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage781_790_recovery_readiness.py"
s=importlib.util.spec_from_file_location("stage781",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

NOW="2026-11-23T12:00:00Z"
def manifest():
 return {"schema":"recovery-evidence-v1","artifacts":[
 {"artifact_ref":"backup-1","artifact_type":"backup","sha256":"a"*64,
  "independent_source":True,"collected_at":"2026-11-23T10:00:00Z"},
 {"artifact_ref":"restore-1","artifact_type":"restore_drill","sha256":"b"*64,
  "independent_source":True,"collected_at":"2026-11-23T10:30:00Z"}]}
def receipt(digest):
 return {"drill_ref":"drill-1","environment_ref":"staging-isolated",
 "started_at":"2026-11-23T10:00:00Z","completed_at":"2026-11-23T10:30:00Z",
 "result":"PASS","observed_rto_seconds":120,"observed_rpo_seconds":0,
 "manifest_sha256":digest,"operator_ref":"operator-external"}
def test_manifest_validation_and_duplicate_detection():
 assert m.validate_evidence_manifest(manifest())["status"]=="PASS"
 x=manifest(); x["artifacts"].append(dict(x["artifacts"][0]))
 assert "artifact_2_duplicate_ref" in m.validate_evidence_manifest(x)["issues"]
def test_manifest_rejects_unattested_independence_and_bad_digest():
 x=manifest(); x["artifacts"][0]["independent_source"]=False
 x["artifacts"][1]["sha256"]="bad"
 r=m.validate_evidence_manifest(x)
 assert r["status"]=="BLOCKED"
 assert "independence_cryptographically_proven" in r
 assert r["independence_cryptographically_proven"] is False
def test_drill_receipt_binding_freshness_and_result():
 d="c"*64
 assert m.verify_recovery_drill_receipt(receipt(d),d,NOW)["status"]=="PASS"
 assert "drill_manifest_binding_mismatch" in m.verify_recovery_drill_receipt(receipt(d),"d"*64,NOW)["issues"]
 x=receipt(d); x["result"]="FAIL"
 assert "drill_not_passed" in m.verify_recovery_drill_receipt(x,d,NOW)["issues"]
def test_drill_rejects_stale_future_and_invalid_metrics():
 d="c"*64; x=receipt(d)
 assert "drill_receipt_stale" in m.verify_recovery_drill_receipt(x,d,"2026-12-10T00:00:00Z")["issues"]
 assert "drill_completion_in_future" in m.verify_recovery_drill_receipt(x,d,"2026-11-22T00:00:00Z")["issues"]
 x["observed_rto_seconds"]=-1
 assert "observed_rto_seconds_invalid" in m.verify_recovery_drill_receipt(x,d,NOW)["issues"]
def test_objective_thresholds():
 assert m.evaluate_recovery_objectives({"observed_rto_seconds":120,"observed_rpo_seconds":0},
 {"rto_seconds":180,"rpo_seconds":30})["status"]=="PASS"
 assert "observed_rto_seconds_objective_breached" in m.evaluate_recovery_objectives(
 {"observed_rto_seconds":200,"observed_rpo_seconds":0},{"rto_seconds":180,"rpo_seconds":30})["issues"]
def test_dependencies_fail_closed():
 assert m.validate_dependency_readiness([{"dependency_ref":"db","status":"READY","evidence_ref":"e1"}])["status"]=="PASS"
 assert m.validate_dependency_readiness([{"dependency_ref":"db","status":"UNKNOWN"}])["status"]=="BLOCKED"
def test_recovery_decision_requires_closed_incident_and_cleared_hold():
 good={"status":"PASS"}
 r=m.build_recovery_decision(good,good,good,good,"CLOSED","CLEARED")
 assert r["status"]=="READY_FOR_AUTHORIZED_REVIEW"
 assert r["authorization_granted"] is False
 assert m.build_recovery_decision(good,good,good,good,"OPEN","CLEARED")["status"]=="BLOCKED"
 assert m.build_recovery_decision(good,good,good,good,"CLOSED","HOLD")["status"]=="BLOCKED"
def test_stage_790_never_resumes_workload_or_authorizes():
 good={"status":"READY_FOR_AUTHORIZED_REVIEW"}
 r=m.stage_790_recovery_gate(good,{"authenticated":True})
 assert r["restart_authorized"] is False and r["workload_resumed"] is False
 assert m.stage_790_recovery_gate({"status":"BLOCKED"})["status"]=="BLOCKED"
