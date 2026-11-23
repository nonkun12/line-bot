import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage721_730_evaluation_integrity.py"
s=importlib.util.spec_from_file_location("stage721",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def good():
 return {"integrity_ref":"integrity","evaluation_ref":"evaluation","audit_ref":"audit","created_at":"2026-11-23T12:00:00Z",
 "manifest":{"manifest_ref":"manifest","schema_ref":"schema","canonicalization_ref":"canon","root_digest":"a"*64,"status":"PASS_DECLARED","canonicalized":False,"digest_recomputed":False},
 "artifacts":[{"artifact_ref":"artifact","role_ref":"role","source_ref":"source","media_type_ref":"type","digest_ref":"digest","sha256":"b"*64,"status":"PASS_DECLARED","retrieved":False,"digest_recomputed":False}],
 "environment":{"environment_ref":"environment","runtime_ref":"runtime","dependency_lock_ref":"lock","hardware_ref":"hardware","configuration_ref":"config","fingerprint_sha256":"c"*64,"status":"PASS_DECLARED","fingerprint_recomputed":False},
 "attestation":{"attestation_ref":"attest","issuer_ref":"issuer","subject_ref":"subject","key_ref":"key","signature_ref":"signature","policy_ref":"policy","status":"PASS_DECLARED","signature_verified":False,"issuer_authenticated":False,"issued_at":"2026-11-23T11:00:00Z"},
 "evaluator":{"evaluator_ref":"evaluator","independence_basis_ref":"basis","conflict_check_ref":"conflicts","assessment_ref":"assessment","independent":True,"conflicts_disclosed":True,"identity_authenticated":False,"assessment_executed":False},
 "statistics":{"analysis_plan_ref":"plan","method_ref":"method","hypothesis_ref":"hypothesis","threshold_ref":"threshold","result_ref":"result","uncertainty_ref":"uncertainty","status":"PASS_DECLARED","preregistered":True,"recomputed":False,"effect_size":0.2,"confidence_level":0.95,"p_value":0.01,"minimum_effect":0.1,"decision":"ACCEPT_DECLARED"},
 "reproduction":{"package_ref":"package","instructions_ref":"instructions","dependency_lock_ref":"lock","seed_ref":"seed","expected_output_ref":"expected","attempt_log_ref":"attempt","status":"PASS_DECLARED","attempted":False,"outputs_compared":False,"independent_reproducer":True,"reproducer_authenticated":False},
 "provenance":[{"event_ref":"event","actor_ref":"actor","input_ref":"input","output_ref":"output","previous_event_ref":"previous","evidence_ref":"evidence","status":"PASS_DECLARED","chain_verified":False}],
 "limitations":[{"limitation_ref":"limitation","impact_ref":"impact","owner_ref":"owner","disposition":"MITIGATION_PLANNED"}]}

def test_complete_declarations_are_not_verified():
 r=m.stage_730_evaluation_integrity_gate(good())
 assert r["status"]=="DECLARATIONS_COMPLETE"
 assert r["gate"]=="READY_FOR_EXTERNAL_VERIFICATION"
 assert r["evaluation_integrity_verified"] is False
 assert r["capability_improvement_verified"] is False

def test_missing_or_wrong_record_blocks():
 x=good(); del x["manifest"]
 assert "manifest" in m.validate_evaluation_integrity(x)["missing"]
 assert m.validate_evaluation_integrity([])["status"]=="BLOCKED"

def test_digest_format_and_duplicate_artifacts():
 x=good(); x["artifacts"][0]["sha256"]="not-a-digest"
 assert "artifact_sha256_invalid" in m.validate_evaluation_integrity(x)["issues"]
 x=good(); x["artifacts"].append(dict(x["artifacts"][0]))
 assert "artifact_refs_duplicate" in m.validate_evaluation_integrity(x)["issues"]

def test_signature_and_hash_verification_not_claimed():
 x=good(); x["attestation"]["signature_verified"]=True
 assert "signature_verification_must_not_be_claimed" in m.validate_evaluation_integrity(x)["issues"]
 x=good(); x["manifest"]["digest_recomputed"]=True
 assert "digest_recomputation_must_not_be_claimed" in m.validate_evaluation_integrity(x)["issues"]

def test_evaluator_and_reproducer_boundaries():
 x=good(); x["evaluator"]["identity_authenticated"]=True
 assert "evaluator_authentication_must_not_be_claimed" in m.validate_evaluation_integrity(x)["issues"]
 x=good(); x["reproduction"]["attempted"]=True
 assert "reproduction_attempt_must_not_be_claimed" in m.validate_evaluation_integrity(x)["issues"]

def test_statistics_ranges_and_finite_values():
 x=good(); x["statistics"]["p_value"]=1.2
 assert "statistics_p_value_out_of_range" in m.validate_evaluation_integrity(x)["issues"]
 x=good(); x["statistics"]["effect_size"]=float("inf")
 assert "statistics_effect_size_invalid" in m.validate_evaluation_integrity(x)["issues"]
 x=good(); x["statistics"]["confidence_level"]=True
 assert "statistics_confidence_level_invalid" in m.validate_evaluation_integrity(x)["issues"]

def test_provenance_and_limitations_fail_closed():
 x=good(); x["provenance"][0]["chain_verified"]=True
 assert "provenance_chain_verification_must_not_be_claimed" in m.validate_evaluation_integrity(x)["issues"]
 x=good(); x["limitations"][0]["disposition"]="BLOCKING"
 assert "limitation_not_accepted" in m.validate_evaluation_integrity(x)["issues"]
