import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage561",Path(__file__).parents[1]/"core/ai_factory_stage561_565_evidence_integrity.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"evidence_id":"ev1","content_digest":"0123456789abcdef0123","digest_algorithm":"sha256","source_ref":"src1",
 "parent_evidence_refs":["parent1"],"lineage_root":"root1","lineage_complete":True,
 "attestation_ref":"att1","attestor_role":"independent","verification_method":"cryptographic",
 "append_only_log_ref":"log1","log_sequence":1,"retention_declaration":"retained"}

def test_complete_metadata_still_requires_review():
 x=m.stage_565_integrity_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["digest_verified"] is False and x["tamper_resistance_proven"] is False

def test_bad_digest_and_lineage_block():
 x=good();x["content_digest"]="short";x["lineage_complete"]=False
 assert m.validate_evidence_integrity(x)["status"]=="BLOCKED"

def test_invalid_attestation_and_sequence_block():
 x=good();x["attestor_role"]="self";x["log_sequence"]=True
 assert m.validate_evidence_integrity(x)["status"]=="BLOCKED"

def test_duplicate_parent_refs_block():
 x=good();x["parent_evidence_refs"]=["p","p"]
 assert m.validate_evidence_integrity(x)["status"]=="BLOCKED"
