"""Evidence integrity and tamper-resistance declarations for AI Factory stages 561-565."""
from __future__ import annotations

REQUIRED={
 561:("evidence_id","content_digest","digest_algorithm","source_ref"),
 562:("parent_evidence_refs","lineage_root","lineage_complete"),
 563:("attestation_ref","attestor_role","verification_method"),
 564:("append_only_log_ref","log_sequence","retention_declaration"),
}

def _missing(obj,keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",[],{})]

def _refs(v):
 return isinstance(v,list) and all(isinstance(x,str) and x for x in v) and len(v)==len(set(v))

def validate_evidence_integrity(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 digest=record.get("content_digest")
 algorithm=record.get("digest_algorithm")
 if not isinstance(digest,str) or len(digest)<16:
  issues.append("content_digest_invalid")
 if algorithm not in ("sha256","sha512"):
  issues.append("digest_algorithm_unsupported")
 if not _refs(record.get("parent_evidence_refs")):
  issues.append("parent_evidence_refs_invalid")
 if record.get("lineage_complete") is not True:
  issues.append("lineage_not_declared_complete")
 if record.get("attestor_role") not in ("independent","system"):
  issues.append("attestor_role_invalid")
 if record.get("verification_method") not in ("cryptographic","trusted_external"):
  issues.append("verification_method_invalid")
 seq=record.get("log_sequence")
 if not isinstance(seq,int) or isinstance(seq,bool) or seq<0:
  issues.append("log_sequence_invalid")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"digest_verified":False,"tamper_resistance_proven":False}

def stage_565_integrity_gate(record):
 result=validate_evidence_integrity(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_trust":False}
