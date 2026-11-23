import hashlib
import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage741_750_reproduction_audit.py"
s=importlib.util.spec_from_file_location("stage741",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def sha(b): return hashlib.sha256(b).hexdigest()
def digest(v): return hashlib.sha256(m._canonical(v)).hexdigest()

def plan():
 return {"plan_ref":"plan","protocol_ref":"protocol","command_ref":"command","environment_ref":"env",
 "input_manifest_ref":"input","expected_output_ref":"expected","dependency_lock_ref":"lock",
 "seed_ref":"seed","timeout_policy_ref":"timeout","resource_limit_ref":"limits","rollback_policy_ref":"rollback",
 "owner_ref":"owner","network_access":False,"write_scope":"TEMPORARY_SANDBOX","secret_access":False,
 "production_target":False,"human_review_required":True,"max_duration_seconds":120,"max_output_bytes":4096}

def receipt(ref="attempt-1"):
 out=b"ok\n"; err=b""
 return {"receipt_ref":"receipt-"+ref,"plan_ref":"plan","attempt_ref":ref,"environment_ref":"env",
 "command_ref":"command","input_manifest_ref":"input","output_manifest_ref":"output",
 "stdout_sha256":sha(out),"stderr_sha256":sha(err),"exit_code":0,
 "started_at":"2026-11-23T10:00:00Z","finished_at":"2026-11-23T10:00:01Z",
 "executor_ref":"executor","audit_ref":"audit","execution_performed":True,"signature_verified":False}, {"stdout":out,"stderr":err}

def attempt(ref):
 return {"attempt_ref":ref,"plan_ref":"plan","environment_ref":"env","command_ref":"command",
 "input_manifest_ref":"input","output_manifest_ref":"output","status":"PASS","exit_code":0,
 "stdout_sha256":sha(b"ok\n"),"stderr_sha256":sha(b""),"output_sha256":"a"*64}

def chain():
 a={"event_ref":"e1","previous_digest":None,"event":"planned"}; a["event_digest"]=digest(a)
 b={"event_ref":"e2","previous_digest":a["event_digest"],"event":"completed"}; b["event_digest"]=digest(b)
 return [a,b]

def test_bounded_plan_accepts_only_safe_scope():
 assert m.validate_reproduction_plan(plan())["status"]=="PASS"
 x=plan(); x["network_access"]=True
 assert "network_access_must_be_disabled" in m.validate_reproduction_plan(x)["issues"]
 x=plan(); x["production_target"]=True
 assert "production_target_must_be_disabled" in m.validate_reproduction_plan(x)["issues"]

def test_plan_requires_human_review_and_limits():
 x=plan(); x["human_review_required"]=False
 assert "human_review_boundary_missing" in m.validate_reproduction_plan(x)["issues"]
 x=plan(); x["max_duration_seconds"]=99999
 assert "duration_limit_invalid" in m.validate_reproduction_plan(x)["issues"]

def test_receipt_verifies_supplied_stdout_and_stderr_bytes():
 r,payloads=receipt()
 assert m.verify_execution_receipt(r,payloads)["status"]=="PASS"
 payloads["stdout"]=b"tampered"
 assert "stdout_digest_mismatch" in m.verify_execution_receipt(r,payloads)["issues"]

def test_receipt_requires_zero_exit_and_ordered_timestamps():
 r,payloads=receipt(); r["exit_code"]=2
 assert m.verify_execution_receipt(r,payloads)["exit_success"] is False
 r,payloads=receipt(); r["finished_at"]="2026-11-23T09:00:00Z"
 assert "execution_time_order_invalid" in m.verify_execution_receipt(r,payloads)["issues"]

def test_repeated_attempts_must_match_and_be_unique():
 assert m.compare_reproduction_attempts([attempt("a"),attempt("b")])["status"]=="PASS"
 x=attempt("b"); x["output_sha256"]="f"*64
 assert "reproduction_outputs_not_identical" in m.compare_reproduction_attempts([attempt("a"),x])["issues"]
 assert "attempt_ref_duplicate:b" in m.compare_reproduction_attempts([attempt("b"),attempt("b")])["issues"]

def test_audit_chain_detects_tampering():
 events=chain()
 assert m.verify_audit_events(events)["status"]=="PASS"
 events[1]["event"]="tampered"
 assert "audit_event_digest_mismatch:1" in m.verify_audit_events(events)["issues"]

def test_gate_fails_closed_on_bad_receipt_or_missing_audit():
 r,payloads=receipt()
 result=m.stage_750_reproduction_audit_gate(plan(),[r],[attempt("a"),attempt("b")],chain(),{"attempt-1":payloads})
 assert result["status"]=="REPRODUCTION_EVIDENCE_VALIDATED"
 assert result["gate"]=="READY_FOR_HUMAN_REVIEW"
 assert result["reproduction_verified_by_validator"] is False
 result=m.stage_750_reproduction_audit_gate(plan(),[r],[attempt("a"),attempt("b")],[],{"attempt-1":payloads})
 assert result["status"]=="BLOCKED"

def test_signature_and_identity_are_not_claimed():
 r,payloads=receipt(); r["signature_verified"]=True
 assert "signature_verification_not_supported" in m.verify_execution_receipt(r,payloads)["issues"]
