import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage751_760_attestation_trust.py"
s=importlib.util.spec_from_file_location("stage751",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

KEY=b"K"*32
NOW="2026-11-23T12:00:00Z"

def policy():
 return {"audience":"ai-factory-review","max_lifetime_seconds":3600,
 "keys":{"key-1":{"key":KEY,"issuer_ref":"issuer-1","status":"ACTIVE","allowed_scopes":["reproduction:review","evidence:verify"]}}}

def envelope(nonce="nonce-abcdefghijklmnop",scope="reproduction:review"):
 e={"attestation_ref":"att-1","issuer_ref":"issuer-1","key_id":"key-1",
 "audience":"ai-factory-review","scope":scope,"subject_digest":"a"*64,
 "issued_at":"2026-11-23T11:30:00Z","expires_at":"2026-11-23T12:30:00Z",
 "nonce":nonce}
 e["signature"]=m.sign_envelope_hmac(e,KEY)
 return e

def test_valid_hmac_confirms_only_key_possession():
 r=m.verify_attestation(envelope(),policy(),NOW,[])
 assert r["status"]=="PASS"
 assert r["key_possession_verified"] is True
 assert r["human_identity_authenticated"] is False
 assert r["non_repudiation_established"] is False

def test_tampered_payload_and_signature_block():
 e=envelope(); e["scope"]="admin"
 assert "signature_mismatch" in m.verify_attestation(e,policy(),NOW,[])["issues"]
 e=envelope(); e["signature"]="0"*64
 assert "signature_mismatch" in m.verify_attestation(e,policy(),NOW,[])["issues"]

def test_unknown_revoked_and_wrong_issuer_keys_block():
 e=envelope(); e["key_id"]="unknown"
 assert "key_not_trusted" in m.verify_attestation(e,policy(),NOW,[])["issues"]
 p=policy(); p["keys"]["key-1"]["status"]="REVOKED"
 assert "key_not_active" in m.verify_attestation(envelope(),p,NOW,[])["issues"]
 p=policy(); p["keys"]["key-1"]["issuer_ref"]="other"
 assert "issuer_key_binding_mismatch" in m.verify_attestation(envelope(),p,NOW,[])["issues"]

def test_audience_scope_and_expiry_enforced():
 e=envelope(); e["audience"]="other"
 assert "audience_mismatch" in m.verify_attestation(e,policy(),NOW,[])["issues"]
 e=envelope(scope="model:write")
 assert "scope_not_authorized" in m.verify_attestation(e,policy(),NOW,[])["issues"]
 assert "attestation_expired" in m.verify_attestation(envelope(),policy(),"2026-11-23T13:00:00Z",[])["issues"]

def test_lifetime_future_time_and_nonce_replay_block():
 e=envelope(); e["expires_at"]="2026-11-24T12:30:00Z"; e["signature"]=m.sign_envelope_hmac(e,KEY)
 assert "attestation_lifetime_exceeds_policy" in m.verify_attestation(e,policy(),NOW,[])["issues"]
 assert "attestation_not_yet_valid" in m.verify_attestation(envelope(),"".join([]) if False else policy(),"2026-11-23T10:00:00Z",[])["issues"]
 assert "nonce_replay_detected" in m.verify_attestation(envelope(),policy(),NOW,["nonce-abcdefghijklmnop"])["issues"]

def test_short_key_and_bad_nonce_block():
 with __import__("pytest").raises(ValueError): m.sign_envelope_hmac(envelope(),b"short")
 e=envelope("short")
 assert "nonce_invalid" in m.verify_attestation(e,policy(),NOW,[])["issues"]

def test_batch_detects_nonce_reuse_within_batch():
 a=envelope("nonce-abcdefghijklmnop")
 b=envelope("nonce-abcdefghijklmnop")
 b["attestation_ref"]="att-2"
 b["signature"]=m.sign_envelope_hmac(b,KEY)
 r=m.verify_attestation_batch([a,b],policy(),NOW,[])
 assert r["status"]=="BLOCKED"
 assert any("nonce_replay_detected" in x for x in r["issues"])

def test_gate_requires_scopes_and_never_authenticates_identity():
 a=envelope("nonce-abcdefghijklmnop","reproduction:review")
 b=envelope("nonce-qrstuvwxyzabcdef","evidence:verify")
 r=m.stage_760_attestation_trust_gate([a,b],policy(),NOW,[],["reproduction:review","evidence:verify"])
 assert r["status"]=="TRUSTED_KEY_POSSESSION_CONFIRMED"
 assert r["human_identity_authenticated"] is False
 assert r["nonce_ledger_persisted"] is False
