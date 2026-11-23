import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("stage631", Path(__file__).parents[1] / "core/ai_factory_stage631_640_attestation_chain.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def good():
    return {
      "subject_ref":"package-1","policy_version":"trust-policy-v1",
      "trust_policy":{"policy_ref":"policy-1","allowed_issuer_refs":["issuer-1"],"allowed_algorithms":["ED25519"]},
      "revocation_snapshot":{"snapshot_ref":"rev-1","checked_at":"2026-11-23T11:00:00Z",
        "status":"REVOCATION_STATUS_DECLARED_CURRENT","revoked_key_refs":[]},
      "timestamp_evidence":{"authority_ref":"tsa-1","timestamp_ref":"ts-1","subject_digest_ref":"digest-1",
        "issued_at":"2026-11-23T11:03:00Z","status":"TIMESTAMP_DECLARED_VALID"},
      "scope":{"resource_ref":"package-1","permitted_claims":["integrity","origin"],"wildcard_scope":False},
      "attestations":[{"attestation_ref":"att-1","subject_ref":"package-1","issuer_ref":"issuer-1",
        "key_ref":"key-1","algorithm":"ED25519","signature_ref":"sig-1",
        "payload_digest_declared":"a"*64,"sequence":0,"signed_at":"2026-11-23T11:02:00Z",
        "claims":["integrity"]}],
      "created_at":"2026-11-23T11:04:00Z","automatic_verification":False}

def test_complete_chain_is_review_only():
    r=m.stage_640_attestation_chain_gate(good())
    assert r["status"]=="DECLARATIONS_COMPLETE"
    assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
    assert r["cryptographic_signatures_verified"] is False
    assert r["trust_roots_verified"] is False
    assert r["authorization_granted"] is False

def test_missing_and_malformed_records_block():
    x=good(); del x["policy_version"]
    assert "policy_version" in m.validate_attestation_chain(x)["missing"]
    assert m.validate_attestation_chain(None)["status"]=="BLOCKED"

def test_untrusted_issuer_algorithm_and_revoked_key_block():
    x=good(); x["attestations"][0]["issuer_ref"]="outsider"
    assert "attestation_issuer_not_allowed" in m.validate_attestation_chain(x)["issues"]
    x=good(); x["attestations"][0]["algorithm"]="UNKNOWN"
    assert "attestation_algorithm_not_allowed" in m.validate_attestation_chain(x)["issues"]
    x=good(); x["revocation_snapshot"]["revoked_key_refs"]=["key-1"]
    assert "attestation_key_declared_revoked" in m.validate_attestation_chain(x)["issues"]

def test_subject_scope_and_digest_are_bound():
    x=good(); x["attestations"][0]["subject_ref"]="other"
    assert "attestation_subject_mismatch" in m.validate_attestation_chain(x)["issues"]
    x=good(); x["attestations"][0]["claims"]=["admin"]
    assert "attestation_claim_out_of_scope" in m.validate_attestation_chain(x)["issues"]
    x=good(); x["attestations"][0]["payload_digest_declared"]="invalid"
    assert "attestation_digest_declaration_invalid" in m.validate_attestation_chain(x)["issues"]

def test_chain_sequence_and_time_order_are_checked():
    x=good(); x["attestations"].append({**x["attestations"][0],"attestation_ref":"att-2","key_ref":"key-2","sequence":2,"signed_at":"2026-11-23T11:01:00Z"})
    r=m.validate_attestation_chain(x)
    assert "attestation_sequence_not_contiguous" in r["issues"]
    assert "attestation_time_order_invalid" in r["issues"]

def test_timestamp_and_revocation_declarations_must_be_valid():
    x=good(); x["timestamp_evidence"]["status"]="UNKNOWN"
    assert "timestamp_status_not_valid_declared" in m.validate_attestation_chain(x)["issues"]
    x=good(); x["revocation_snapshot"]["status"]="UNKNOWN"
    assert "revocation_status_not_current_declared" in m.validate_attestation_chain(x)["issues"]

def test_wildcard_scope_and_auto_verification_are_forbidden():
    x=good(); x["scope"]["wildcard_scope"]=True
    assert "wildcard_scope_must_be_false" in m.validate_attestation_chain(x)["issues"]
    x=good(); x["automatic_verification"]=True
    assert "automatic_verification_must_be_false" in m.validate_attestation_chain(x)["issues"]
