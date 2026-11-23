"""Attestation-chain metadata checks (AI Factory Stages 631-640).

This module validates declarations only. It does not perform cryptographic,
PKI, revocation, or trusted-timestamp verification.
"""
from __future__ import annotations
import re
from datetime import datetime

REQUIRED = ("subject_ref", "attestations", "trust_policy", "revocation_snapshot",
            "timestamp_evidence", "scope", "policy_version", "created_at",
            "automatic_verification")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def _text(v):
    return isinstance(v, str) and bool(v.strip())

def _time(v):
    if not _text(v):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else None

def _texts(v, allow_empty=False):
    return (isinstance(v, list) and (allow_empty or bool(v))
            and all(_text(x) for x in v) and len(v) == len(set(v)))

def validate_attestation_chain(record):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}
    missing = [k for k in REQUIRED if k not in record or record[k] is None]
    issues = []
    if not _text(record.get("subject_ref")):
        issues.append("subject_ref_invalid")
    if not _text(record.get("policy_version")):
        issues.append("policy_version_invalid")
    if _time(record.get("created_at")) is None:
        issues.append("created_at_invalid")
    if record.get("automatic_verification") is not False:
        issues.append("automatic_verification_must_be_false")

    policy = record.get("trust_policy")
    if not isinstance(policy, dict):
        issues.append("trust_policy_invalid")
        issuers, algorithms = set(), set()
    else:
        issuers_raw, algorithms_raw = policy.get("allowed_issuer_refs"), policy.get("allowed_algorithms")
        if not _texts(issuers_raw): issues.append("allowed_issuers_invalid")
        if not _texts(algorithms_raw): issues.append("allowed_algorithms_invalid")
        issuers = set(issuers_raw) if _texts(issuers_raw) else set()
        algorithms = set(algorithms_raw) if _texts(algorithms_raw) else set()
        if not _text(policy.get("policy_ref")): issues.append("trust_policy_ref_invalid")

    rev = record.get("revocation_snapshot")
    if not isinstance(rev, dict):
        issues.append("revocation_snapshot_invalid")
        revoked = set()
    else:
        if not _text(rev.get("snapshot_ref")): issues.append("revocation_snapshot_ref_invalid")
        if _time(rev.get("checked_at")) is None: issues.append("revocation_checked_at_invalid")
        if rev.get("status") != "REVOCATION_STATUS_DECLARED_CURRENT":
            issues.append("revocation_status_not_current_declared")
        raw = rev.get("revoked_key_refs")
        if not _texts(raw, allow_empty=True): issues.append("revoked_keys_invalid")
        revoked = set(raw) if _texts(raw, allow_empty=True) else set()

    ts = record.get("timestamp_evidence")
    if not isinstance(ts, dict):
        issues.append("timestamp_evidence_invalid")
    else:
        for k in ("authority_ref", "timestamp_ref", "subject_digest_ref"):
            if not _text(ts.get(k)): issues.append(f"timestamp_{k}_invalid")
        if _time(ts.get("issued_at")) is None: issues.append("timestamp_issued_at_invalid")
        if ts.get("status") != "TIMESTAMP_DECLARED_VALID":
            issues.append("timestamp_status_not_valid_declared")

    scope = record.get("scope")
    if not isinstance(scope, dict):
        issues.append("scope_invalid")
    else:
        if not _text(scope.get("resource_ref")): issues.append("scope_resource_ref_invalid")
        if not _texts(scope.get("permitted_claims")): issues.append("scope_claims_invalid")
        if scope.get("wildcard_scope") is not False: issues.append("wildcard_scope_must_be_false")

    chain = record.get("attestations")
    if not isinstance(chain, list) or not chain:
        issues.append("attestations_invalid")
        chain = []
    refs, keys, seqs, times = [], [], [], []
    expected_subject = record.get("subject_ref")
    allowed_claims = set(scope.get("permitted_claims", [])) if isinstance(scope, dict) and isinstance(scope.get("permitted_claims"), list) else set()
    for item in chain:
        if not isinstance(item, dict):
            issues.append("attestation_invalid")
            continue
        for k in ("attestation_ref", "subject_ref", "issuer_ref", "key_ref",
                  "algorithm", "signature_ref", "payload_digest_declared"):
            if not _text(item.get(k)): issues.append(f"attestation_{k}_invalid")
        if _text(item.get("attestation_ref")): refs.append(item["attestation_ref"])
        if _text(item.get("key_ref")): keys.append(item["key_ref"])
        if item.get("subject_ref") != expected_subject: issues.append("attestation_subject_mismatch")
        if item.get("issuer_ref") not in issuers: issues.append("attestation_issuer_not_allowed")
        if item.get("algorithm") not in algorithms: issues.append("attestation_algorithm_not_allowed")
        if item.get("key_ref") in revoked: issues.append("attestation_key_declared_revoked")
        digest = item.get("payload_digest_declared")
        if not _text(digest) or not HEX64.fullmatch(digest): issues.append("attestation_digest_declaration_invalid")
        seq = item.get("sequence")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            issues.append("attestation_sequence_invalid")
        else: seqs.append(seq)
        signed = _time(item.get("signed_at"))
        if signed is None: issues.append("attestation_signed_at_invalid")
        else: times.append(signed)
        claims = item.get("claims")
        if not _texts(claims): issues.append("attestation_claims_invalid")
        elif not set(claims).issubset(allowed_claims): issues.append("attestation_claim_out_of_scope")
    if len(refs) != len(set(refs)): issues.append("attestation_refs_duplicate")
    if len(keys) != len(set(keys)): issues.append("attestation_keys_duplicate")
    if len(seqs) != len(chain) or sorted(seqs) != list(range(len(chain))):
        issues.append("attestation_sequence_not_contiguous")
    if len(times) == len(chain) and times != sorted(times):
        issues.append("attestation_time_order_invalid")
    if isinstance(ts, dict) and _time(ts.get("issued_at")) is not None and times:
        if _time(ts["issued_at"]) < times[-1]:
            issues.append("timestamp_precedes_final_attestation")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": sorted(set(issues))}
    return {"status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
            "cryptographic_signatures_verified": False, "issuer_identity_authenticated": False,
            "trust_roots_verified": False, "revocation_checked_externally": False,
            "timestamp_authority_verified": False, "claim_truth_verified": False}

def stage_640_attestation_chain_gate(record):
    result = validate_attestation_chain(record)
    ready = result["status"] == "DECLARATIONS_COMPLETE"
    return {**result, "gate": "READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
            "automatic_verification": False, "authorization_granted": False,
            "release_authorized": False}
