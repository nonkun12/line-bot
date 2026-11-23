"""Trust-evaluation record declarations (AI Factory Stages 641-650).

This module validates caller-supplied evaluation metadata only. It does not
verify cryptography, authenticate reviewers, evaluate live trust stores, or
grant permissions.
"""
from __future__ import annotations
import re
from datetime import datetime

REQUIRED = (
    "subject_ref", "attestation_chain_ref", "policy_ref", "evaluation_ref",
    "evaluator_ref", "evaluation_time", "decision", "scope",
    "evidence_coverage", "exceptions", "conflict_check", "validity",
    "audit_record_ref", "automatic_trust", "created_at",
)
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DECISIONS = {"TRUST_ACCEPTED_DECLARED", "TRUST_REJECTED_DECLARED",
             "TRUST_INDETERMINATE_DECLARED", "TRUST_REVOKED_DECLARED"}
EXCEPTION_STATES = {"OPEN", "MITIGATED_DECLARED", "WAIVED_DECLARED", "CLOSED_DECLARED"}

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

def _unique_texts(v, allow_empty=False):
    return (isinstance(v, list) and (allow_empty or bool(v))
            and all(_text(x) for x in v) and len(v) == len(set(v)))

def validate_trust_evaluation(record):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}
    missing = [k for k in REQUIRED if k not in record or record[k] is None]
    issues = []
    for field in ("subject_ref", "attestation_chain_ref", "policy_ref",
                  "evaluation_ref", "evaluator_ref", "audit_record_ref"):
        if not _text(record.get(field)):
            issues.append(f"{field}_invalid")
    created = _time(record.get("created_at"))
    evaluated = _time(record.get("evaluation_time"))
    if created is None: issues.append("created_at_invalid")
    if evaluated is None: issues.append("evaluation_time_invalid")
    if created is not None and evaluated is not None and evaluated > created:
        issues.append("evaluation_after_record_creation")
    if record.get("decision") not in DECISIONS:
        issues.append("decision_invalid")
    if record.get("automatic_trust") is not False:
        issues.append("automatic_trust_must_be_false")

    scope = record.get("scope")
    if not isinstance(scope, dict):
        issues.append("scope_invalid")
    else:
        for k in ("resource_ref", "policy_scope_ref"):
            if not _text(scope.get(k)): issues.append(f"scope_{k}_invalid")
        claims = scope.get("permitted_claims")
        if not _unique_texts(claims): issues.append("scope_permitted_claims_invalid")
        if scope.get("wildcard") is not False: issues.append("scope_wildcard_must_be_false")

    coverage = record.get("evidence_coverage")
    if not isinstance(coverage, dict):
        issues.append("evidence_coverage_invalid")
    else:
        chain_refs = coverage.get("attestation_refs")
        checked_refs = coverage.get("checked_attestation_refs")
        if not _unique_texts(chain_refs): issues.append("coverage_attestation_refs_invalid")
        if not _unique_texts(checked_refs): issues.append("coverage_checked_refs_invalid")
        if _unique_texts(chain_refs) and _unique_texts(checked_refs):
            if not set(checked_refs).issubset(set(chain_refs)):
                issues.append("coverage_contains_unknown_attestations")
            if set(checked_refs) != set(chain_refs):
                issues.append("coverage_incomplete")
        digest = coverage.get("manifest_digest_declared")
        if not _text(digest) or not DIGEST_RE.fullmatch(digest):
            issues.append("coverage_manifest_digest_invalid")
        if coverage.get("complete") is not True:
            issues.append("coverage_not_declared_complete")

    exceptions = record.get("exceptions")
    if not isinstance(exceptions, list):
        issues.append("exceptions_invalid")
        exceptions = []
    exception_refs = []
    for item in exceptions:
        if not isinstance(item, dict):
            issues.append("exception_record_invalid")
            continue
        for k in ("exception_ref", "reason_code", "owner_ref"):
            if not _text(item.get(k)): issues.append(f"exception_{k}_invalid")
        if _text(item.get("exception_ref")): exception_refs.append(item["exception_ref"])
        if item.get("state") not in EXCEPTION_STATES:
            issues.append("exception_state_invalid")
        if item.get("state") in {"WAIVED_DECLARED", "MITIGATED_DECLARED", "CLOSED_DECLARED"}:
            if not _text(item.get("resolution_evidence_ref")):
                issues.append("exception_resolution_evidence_missing")
        if item.get("state") == "OPEN" and record.get("decision") == "TRUST_ACCEPTED_DECLARED":
            issues.append("accepted_decision_with_open_exception")
    if len(exception_refs) != len(set(exception_refs)):
        issues.append("exception_refs_duplicate")

    conflict = record.get("conflict_check")
    if not isinstance(conflict, dict):
        issues.append("conflict_check_invalid")
    else:
        if conflict.get("status") not in ("NO_CONFLICT_DECLARED", "CONFLICT_DECLARED", "UNKNOWN"):
            issues.append("conflict_status_invalid")
        if not _text(conflict.get("check_ref")): issues.append("conflict_check_ref_invalid")
        if conflict.get("status") == "CONFLICT_DECLARED" and record.get("decision") == "TRUST_ACCEPTED_DECLARED":
            issues.append("accepted_decision_with_declared_conflict")
        if conflict.get("status") == "UNKNOWN" and record.get("decision") == "TRUST_ACCEPTED_DECLARED":
            issues.append("accepted_decision_with_unknown_conflict")

    validity = record.get("validity")
    if not isinstance(validity, dict):
        issues.append("validity_invalid")
    else:
        start, end = _time(validity.get("valid_from")), _time(validity.get("valid_until"))
        if start is None or end is None or end <= start:
            issues.append("validity_window_invalid")
        if evaluated is not None and start is not None and end is not None:
            if evaluated < start or evaluated >= end:
                issues.append("evaluation_outside_validity_window")
        if not _text(validity.get("policy_expiry_ref")):
            issues.append("policy_expiry_ref_invalid")
        if validity.get("renewal_required") is not True:
            issues.append("renewal_must_be_required")

    if record.get("decision") == "TRUST_ACCEPTED_DECLARED":
        if isinstance(coverage, dict) and coverage.get("complete") is not True:
            issues.append("acceptance_requires_complete_coverage")
        if exceptions:
            if any(not isinstance(x, dict) or x.get("state") not in {"MITIGATED_DECLARED", "WAIVED_DECLARED", "CLOSED_DECLARED"} for x in exceptions):
                issues.append("acceptance_has_unresolved_exceptions")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": sorted(set(issues))}
    return {
        "status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
        "cryptographic_chain_verified": False, "evaluator_authenticated": False,
        "policy_semantics_executed": False, "conflicts_independently_checked": False,
        "revocation_checked_live": False, "decision_truth_verified": False,
    }

def stage_650_trust_evaluation_gate(record):
    result = validate_trust_evaluation(record)
    ready = result["status"] == "DECLARATIONS_COMPLETE"
    return {
        **result,
        "gate": "READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
        "trust_granted": False, "authorization_granted": False,
        "automatic_trust": False, "release_authorized": False,
    }
