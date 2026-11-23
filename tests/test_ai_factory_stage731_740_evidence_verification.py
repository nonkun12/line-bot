import hashlib
import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage731_740_evidence_verification.py"
s=importlib.util.spec_from_file_location("stage731",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def digest(v): return hashlib.sha256(m.canonical_json_bytes(v)).hexdigest()

def manifest():
 body={"manifest_ref":"m1","schema_version":"1","artifact_refs":["a1"]}
 return {**body,"root_digest":digest(body)}

def artifact():
 b=b"evidence bytes"
 return [{"artifact_ref":"a1","sha256":m.sha256_hex(b)}],{"a1":b}

def chain():
 first={"event_ref":"e1","previous_digest":None,"action":"created"}
 first["event_digest"]=digest(first)
 second={"event_ref":"e2","previous_digest":first["event_digest"],"action":"reviewed"}
 second["event_digest"]=digest(second)
 return [first,second]

def test_artifact_bytes_are_really_hashed():
 a,payloads=artifact()
 assert m.verify_artifact_inventory(a,payloads)["status"]=="PASS"
 payloads["a1"]=b"tampered"
 assert "artifact_digest_mismatch:a1" in m.verify_artifact_inventory(a,payloads)["issues"]

def test_artifact_missing_extra_duplicate_and_invalid():
 a,payloads=artifact()
 assert m.verify_artifact_inventory(a,{})["status"]=="BLOCKED"
 assert "unreferenced_payloads_present" in m.verify_artifact_inventory(a,{"a1":payloads["a1"],"extra":b"x"})["issues"]
 assert "artifact_ref_duplicate" in m.verify_artifact_inventory(a+[a[0]],payloads)["issues"]
 assert m.verify_artifact_inventory(a,{"a1":"not bytes"})["status"]=="BLOCKED"

def test_canonical_manifest_digest():
 x=manifest()
 assert m.verify_manifest_digest(x)["status"]=="PASS"
 x["schema_version"]="2"
 assert "manifest_digest_mismatch" in m.verify_manifest_digest(x)["issues"]
 assert m.verify_manifest_digest({"root_digest":"0"*64,"bad":float("nan")})["status"]=="BLOCKED"

def test_provenance_chain_and_tampering():
 events=chain()
 assert m.verify_provenance_chain(events)["status"]=="PASS"
 events[1]["action"]="rewritten"
 assert "event_digest_mismatch:1" in m.verify_provenance_chain(events)["issues"]

def test_provenance_reordering_or_duplicate_blocks():
 events=chain()
 assert "previous_digest_mismatch:0" in m.verify_provenance_chain(events[1:])["issues"]
 events=chain()
 assert any("event_ref_duplicate" in x for x in m.verify_provenance_chain(events+[events[-1]])["issues"])

def test_metric_arithmetic_detects_regression_and_threshold():
 good={"baseline_value":10.0,"candidate_value":12.0,"minimum_improvement":1.0,"maximum_regression":0.5,"direction":"HIGHER_IS_BETTER"}
 assert m.verify_metric_arithmetic([good])["status"]=="PASS"
 bad={**good,"candidate_value":8.0}
 assert "metric_regression:0" in m.verify_metric_arithmetic([bad])["issues"]
 low={**good,"direction":"LOWER_IS_BETTER","candidate_value":9.8}
 assert "metric_improvement_below_threshold:0" in m.verify_metric_arithmetic([low])["issues"]

def test_bool_nan_and_unsupported_direction_rejected():
 x={"baseline_value":True,"candidate_value":2.0,"minimum_improvement":0.1,"maximum_regression":0.1,"direction":"HIGHER_IS_BETTER"}
 assert "metric_numeric_invalid:0" in m.verify_metric_arithmetic([x])["issues"]
 x={**x,"baseline_value":1.0,"direction":"TARGET_RANGE"}
 assert "metric_direction_unsupported:0" in m.verify_metric_arithmetic([x])["issues"]

def test_integrated_gate_never_claims_full_capability_verification():
 a,payloads=artifact()
 r=m.stage_740_evidence_verification_gate(manifest(),a,payloads,chain(),
   [{"baseline_value":1.0,"candidate_value":2.0,"minimum_improvement":0.5,"maximum_regression":0.1,"direction":"HIGHER_IS_BETTER"}])
 assert r["status"]=="INTEGRITY_CHECKS_PASS"
 assert r["gate"]=="PENDING_SIGNATURE_AND_REPRODUCTION_VERIFICATION"
 assert r["capability_improvement_verified"] is False

def test_external_verification_claims_are_rejected():
 a,payloads=artifact()
 r=m.stage_740_evidence_verification_gate(manifest(),a,payloads,chain(),[
  {"baseline_value":1.0,"candidate_value":2.0,"minimum_improvement":0.5,"maximum_regression":0.1,"direction":"HIGHER_IS_BETTER"}],
  signatures_verified=True)
 assert r["status"]=="BLOCKED"
