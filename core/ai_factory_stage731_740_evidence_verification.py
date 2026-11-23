"""Evidence verification primitives (AI Factory Stages 731-740).

Verifies supplied in-memory artifact bytes, canonical manifest digests, and
provenance-chain links. It does not fetch files, authenticate identities,
verify digital signatures, rerun benchmarks, or certify capability gains.
"""
from __future__ import annotations
import hashlib
import json
import math

def _is_sha256(value):
    if not isinstance(value,str) or len(value)!=64: return False
    try: bytes.fromhex(value)
    except ValueError: return False
    return value == value.lower()

def canonical_json_bytes(value):
    """Stable UTF-8 JSON representation used for manifest hashing."""
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def sha256_hex(payload):
    if not isinstance(payload,(bytes,bytearray,memoryview)):
        raise TypeError("payload_must_be_bytes")
    return hashlib.sha256(bytes(payload)).hexdigest()

def verify_artifact_inventory(artifacts, payloads):
    issues=[]
    if not isinstance(artifacts,list) or not artifacts:
        return {"status":"BLOCKED","issues":["artifacts_invalid"],"verified_count":0}
    if not isinstance(payloads,dict):
        return {"status":"BLOCKED","issues":["payloads_invalid"],"verified_count":0}
    seen=set(); verified=0
    for item in artifacts:
        if not isinstance(item,dict):
            issues.append("artifact_record_invalid"); continue
        ref=item.get("artifact_ref"); expected=item.get("sha256")
        if not isinstance(ref,str) or not ref.strip():
            issues.append("artifact_ref_invalid"); continue
        if ref in seen: issues.append("artifact_ref_duplicate"); continue
        seen.add(ref)
        if not _is_sha256(expected):
            issues.append(f"artifact_digest_invalid:{ref}"); continue
        payload=payloads.get(ref)
        if not isinstance(payload,(bytes,bytearray,memoryview)):
            issues.append(f"artifact_payload_missing_or_invalid:{ref}"); continue
        if sha256_hex(payload)!=expected:
            issues.append(f"artifact_digest_mismatch:{ref}"); continue
        verified+=1
    extras=set(payloads)-seen
    if extras: issues.append("unreferenced_payloads_present")
    return {"status":"PASS" if not issues and verified==len(artifacts) else "BLOCKED",
            "issues":sorted(set(issues)),"verified_count":verified}

def verify_manifest_digest(manifest):
    if not isinstance(manifest,dict):
        return {"status":"BLOCKED","issues":["manifest_invalid"]}
    declared=manifest.get("root_digest")
    if not _is_sha256(declared):
        return {"status":"BLOCKED","issues":["manifest_root_digest_invalid"]}
    body={k:v for k,v in manifest.items() if k!="root_digest"}
    try: actual=sha256_hex(canonical_json_bytes(body))
    except (TypeError,ValueError,OverflowError):
        return {"status":"BLOCKED","issues":["manifest_not_canonicalizable"]}
    if actual!=declared:
        return {"status":"BLOCKED","issues":["manifest_digest_mismatch"]}
    return {"status":"PASS","issues":[],"computed_digest":actual}

def verify_provenance_chain(events):
    if not isinstance(events,list) or not events:
        return {"status":"BLOCKED","issues":["provenance_invalid"],"verified_count":0}
    issues=[]; previous=None; seen=set(); count=0
    for index,event in enumerate(events):
        if not isinstance(event,dict):
            issues.append(f"event_invalid:{index}"); continue
        ref=event.get("event_ref"); declared_prev=event.get("previous_digest")
        digest=event.get("event_digest")
        if not isinstance(ref,str) or not ref.strip():
            issues.append(f"event_ref_invalid:{index}")
        elif ref in seen: issues.append(f"event_ref_duplicate:{ref}")
        else: seen.add(ref)
        if declared_prev != previous:
            issues.append(f"previous_digest_mismatch:{index}")
        body={k:v for k,v in event.items() if k!="event_digest"}
        if not _is_sha256(digest):
            issues.append(f"event_digest_invalid:{index}")
        else:
            try: actual=sha256_hex(canonical_json_bytes(body))
            except (TypeError,ValueError,OverflowError):
                issues.append(f"event_not_canonicalizable:{index}"); continue
            if actual!=digest: issues.append(f"event_digest_mismatch:{index}")
            else:
                previous=digest; count+=1
    return {"status":"PASS" if not issues and count==len(events) else "BLOCKED",
            "issues":sorted(set(issues)),"verified_count":count,
            "chain_tip":previous if not issues else None}

def verify_metric_arithmetic(metrics):
    """Checks arithmetic against supplied values; does not validate measurements."""
    if not isinstance(metrics,list) or not metrics:
        return {"status":"BLOCKED","issues":["metrics_invalid"],"checked_count":0}
    issues=[]; checked=0
    for index,item in enumerate(metrics):
        if not isinstance(item,dict):
            issues.append(f"metric_invalid:{index}"); continue
        baseline=item.get("baseline_value"); candidate=item.get("candidate_value")
        minimum=item.get("minimum_improvement"); maximum=item.get("maximum_regression")
        direction=item.get("direction")
        values=(baseline,candidate,minimum,maximum)
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in values):
            issues.append(f"metric_numeric_invalid:{index}"); continue
        if minimum<0 or maximum<0:
            issues.append(f"metric_threshold_negative:{index}"); continue
        delta=candidate-baseline
        if direction=="HIGHER_IS_BETTER":
            if delta < -maximum: issues.append(f"metric_regression:{index}")
            elif delta < minimum: issues.append(f"metric_improvement_below_threshold:{index}")
        elif direction=="LOWER_IS_BETTER":
            if delta > maximum: issues.append(f"metric_regression:{index}")
            elif -delta < minimum: issues.append(f"metric_improvement_below_threshold:{index}")
        else:
            issues.append(f"metric_direction_unsupported:{index}"); continue
        checked+=1
    return {"status":"PASS" if not issues and checked==len(metrics) else "BLOCKED",
            "issues":sorted(set(issues)),"checked_count":checked,
            "measurements_independently_validated":False}

def stage_740_evidence_verification_gate(manifest,artifacts,payloads,provenance,metrics,
                                         signatures_verified=False,reproduction_verified=False,
                                         evaluator_authenticated=False):
    results={
      "manifest":verify_manifest_digest(manifest),
      "artifacts":verify_artifact_inventory(artifacts,payloads),
      "provenance":verify_provenance_chain(provenance),
      "metric_arithmetic":verify_metric_arithmetic(metrics)}
    issues=[f"{name}:{issue}" for name,result in results.items() for issue in result["issues"]]
    if signatures_verified is not False: issues.append("signature_verification_not_supported_here")
    if reproduction_verified is not False: issues.append("reproduction_verification_not_supported_here")
    if evaluator_authenticated is not False: issues.append("evaluator_authentication_not_supported_here")
    passed=not issues and all(x["status"]=="PASS" for x in results.values())
    return {"status":"INTEGRITY_CHECKS_PASS" if passed else "BLOCKED",
            "gate":"PENDING_SIGNATURE_AND_REPRODUCTION_VERIFICATION" if passed else "BLOCKED",
            "issues":sorted(set(issues)),"checks":results,
            "capability_improvement_verified":False,
            "general_intelligence_proven":False,"model_change_authorized":False}
