"""Attestation trust-boundary verification (AI Factory Stages 751-760).

Uses HMAC-SHA256 with caller-supplied trusted key bytes. HMAC authenticates
possession of a shared secret, not a natural person's identity or non-repudiation.
No network, secret store, PKI, or durable replay database is accessed.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from datetime import datetime, timezone

def canonical_envelope_bytes(envelope):
    if not isinstance(envelope,dict):
        raise TypeError("envelope_must_be_object")
    body={k:v for k,v in envelope.items() if k!="signature"}
    return json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def sign_envelope_hmac(envelope,key):
    if not isinstance(key,(bytes,bytearray)) or len(key)<32:
        raise ValueError("trusted_key_must_be_at_least_32_bytes")
    return hmac.new(bytes(key),canonical_envelope_bytes(envelope),hashlib.sha256).hexdigest()

def _time(value):
    if not isinstance(value,str) or not value.strip(): return None
    try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError: return None
    if parsed.tzinfo is None: return None
    return parsed.astimezone(timezone.utc)

def verify_attestation(envelope,trust_policy,now=None,used_nonces=None):
    issues=[]
    if not isinstance(envelope,dict):
        return {"status":"BLOCKED","issues":["envelope_invalid"],"key_possession_verified":False}
    required=("attestation_ref","issuer_ref","key_id","audience","scope","subject_digest",
              "issued_at","expires_at","nonce","signature")
    missing=[k for k in required if k not in envelope or envelope[k] is None]
    for k in required:
        v=envelope.get(k)
        if not isinstance(v,str) or not v.strip(): issues.append(f"{k}_invalid")
    if not isinstance(trust_policy,dict):
        return {"status":"BLOCKED","issues":["trust_policy_invalid"],"missing":missing,
                "key_possession_verified":False}
    keys=trust_policy.get("keys")
    if not isinstance(keys,dict): keys={}
    key_id=envelope.get("key_id")
    entry=keys.get(key_id) if isinstance(key_id,str) else None
    if not isinstance(entry,dict):
        issues.append("key_not_trusted"); entry={}
    key=entry.get("key")
    if not isinstance(key,(bytes,bytearray)) or len(key)<32:
        issues.append("trusted_key_material_invalid")
    if entry.get("status")!="ACTIVE": issues.append("key_not_active")
    if envelope.get("issuer_ref")!=entry.get("issuer_ref"): issues.append("issuer_key_binding_mismatch")
    if envelope.get("audience")!=trust_policy.get("audience"): issues.append("audience_mismatch")
    allowed=entry.get("allowed_scopes")
    if not isinstance(allowed,list) or envelope.get("scope") not in allowed:
        issues.append("scope_not_authorized")
    issued=_time(envelope.get("issued_at")); expires=_time(envelope.get("expires_at"))
    current=_time(now) if now is not None else datetime.now(timezone.utc)
    if issued is None: issues.append("issued_at_invalid")
    if expires is None: issues.append("expires_at_invalid")
    if issued and expires and expires<=issued: issues.append("attestation_expiry_order_invalid")
    if issued and issued>current: issues.append("attestation_not_yet_valid")
    if expires and current>=expires: issues.append("attestation_expired")
    max_age=trust_policy.get("max_lifetime_seconds")
    if not isinstance(max_age,int) or isinstance(max_age,bool) or max_age<=0:
        issues.append("max_lifetime_policy_invalid")
    elif issued and expires and (expires-issued).total_seconds()>max_age:
        issues.append("attestation_lifetime_exceeds_policy")
    nonce=envelope.get("nonce")
    if not isinstance(nonce,str) or len(nonce)<16: issues.append("nonce_invalid")
    if not isinstance(used_nonces,(set,list,tuple)):
        issues.append("nonce_ledger_invalid")
    elif nonce in used_nonces: issues.append("nonce_replay_detected")
    signature=envelope.get("signature")
    if not isinstance(signature,str) or len(signature)!=64:
        issues.append("signature_format_invalid")
    elif isinstance(key,(bytes,bytearray)) and len(key)>=32:
        try: expected=sign_envelope_hmac(envelope,key)
        except (TypeError,ValueError,OverflowError): issues.append("envelope_not_canonicalizable")
        else:
            if not hmac.compare_digest(signature,expected): issues.append("signature_mismatch")
    return {"status":"PASS" if not issues and not missing else "BLOCKED",
            "issues":sorted(set(issues)),"missing":missing,
            "key_possession_verified":not issues and not missing,
            "human_identity_authenticated":False,"non_repudiation_established":False,
            "nonce_consumed":False}

def verify_attestation_batch(envelopes,trust_policy,now,used_nonces):
    if not isinstance(envelopes,list) or not envelopes:
        return {"status":"BLOCKED","issues":["attestations_invalid"],"results":[]}
    if not isinstance(used_nonces,(set,list,tuple)):
        return {"status":"BLOCKED","issues":["nonce_ledger_invalid"],"results":[]}
    seen=set(used_nonces); results=[]; issues=[]
    for index,envelope in enumerate(envelopes):
        result=verify_attestation(envelope,trust_policy,now,seen)
        results.append(result)
        issues.extend(f"attestation_{index}:{x}" for x in result["issues"])
        if result["status"]=="PASS":
            nonce=envelope["nonce"]
            if nonce in seen:
                issues.append(f"attestation_{index}:nonce_replay_detected")
            else:
                seen.add(nonce)
    return {"status":"PASS" if not issues else "BLOCKED",
            "issues":sorted(set(issues)),"results":results,
            "new_nonce_ledger":sorted(seen),"ledger_persisted":False,
            "identity_authenticated":False}

def stage_760_attestation_trust_gate(envelopes,trust_policy,now,used_nonces,
                                     required_scopes=None):
    batch=verify_attestation_batch(envelopes,trust_policy,now,used_nonces)
    issues=list(batch["issues"])
    required_scopes=required_scopes or []
    if not isinstance(required_scopes,list): issues.append("required_scopes_invalid")
    else:
        present={e.get("scope") for e in envelopes if isinstance(e,dict)}
        for scope in required_scopes:
            if scope not in present: issues.append(f"required_scope_missing:{scope}")
    passed=not issues and batch["status"]=="PASS"
    return {"status":"TRUSTED_KEY_POSSESSION_CONFIRMED" if passed else "BLOCKED",
            "gate":"READY_FOR_AUTHORIZED_EXTERNAL_REVIEW" if passed else "BLOCKED",
            "issues":sorted(set(issues)),"attestations":batch["results"],
            "key_possession_verified":passed,"human_identity_authenticated":False,
            "nonce_ledger_persisted":False,"model_change_authorized":False}
