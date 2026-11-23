import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("stage641", Path(__file__).parents[1] / "core/ai_factory_stage641_650_trust_evaluation_record.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def good():
    return {
      "subject_ref":"subject-1","attestation_chain_ref":"chain-1",
      "policy_ref":"policy-v2","evaluation_ref":"evaluation-1",
      "evaluator_ref":"reviewer-1","evaluation_time":"2026-11-23T12:00:00Z",
      "decision":"TRUST_ACCEPTED_DECLARED",
      "scope":{"resource_ref":"package-1","policy_scope_ref":"scope-1",
               "permitted_claims":["integrity"],"wildcard":False},
      "evidence_coverage":{"attestation_refs":["att-1","att-2"],
        "checked_attestation_refs":["att-1","att-2"],"manifest_digest_declared":"a"*64,"complete":True},
      "exceptions":[{"exception_ref":"ex-1","reason_code":"LOW_RISK","owner_ref":"owner-1",
                     "state":"MITIGATED_DECLARED","resolution_evidence_ref":"mitigation-1"}],
      "conflict_check":{"status":"NO_CONFLICT_DECLARED","check_ref":"conflict-check-1"},
      "validity":{"valid_from":"2026-11-23T11:00:00Z","valid_until":"2026-11-24T11:00:00Z",
                  "policy_expiry_ref":"expiry-1","renewal_required":True},
      "audit_record_ref":"audit-1","automatic_trust":False,
      "created_at":"2026-11-23T12:01:00Z"}

def test_complete_evaluation_is_review_only():
    r=m.stage_650_trust_evaluation_gate(good())
    assert r["status"]=="DECLARATIONS_COMPLETE"
    assert r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
    assert r["trust_granted"] is False
    assert r["cryptographic_chain_verified"] is False
    assert r["authorization_granted"] is False

def test_missing_and_bad_input_fail_closed():
    x=good(); del x["policy_ref"]
    assert "policy_ref" in m.validate_trust_evaluation(x)["missing"]
    assert m.validate_trust_evaluation(None)["status"]=="BLOCKED"

def test_coverage_must_be_exact_and_digest_well_formed():
    x=good(); x["evidence_coverage"]["checked_attestation_refs"]=["att-1"]
    assert "coverage_incomplete" in m.validate_trust_evaluation(x)["issues"]
    x=good(); x["evidence_coverage"]["manifest_digest_declared"]="bad"
    assert "coverage_manifest_digest_invalid" in m.validate_trust_evaluation(x)["issues"]

def test_open_exception_or_conflict_prevents_acceptance():
    x=good(); x["exceptions"][0]["state"]="OPEN"
    assert "accepted_decision_with_open_exception" in m.validate_trust_evaluation(x)["issues"]
    x=good(); x["conflict_check"]["status"]="CONFLICT_DECLARED"
    assert "accepted_decision_with_declared_conflict" in m.validate_trust_evaluation(x)["issues"]
    x=good(); x["conflict_check"]["status"]="UNKNOWN"
    assert "accepted_decision_with_unknown_conflict" in m.validate_trust_evaluation(x)["issues"]

def test_scope_is_explicit_and_bounded():
    x=good(); x["scope"]["wildcard"]=True
    assert "scope_wildcard_must_be_false" in m.validate_trust_evaluation(x)["issues"]
    x=good(); x["scope"]["permitted_claims"]=["integrity","integrity"]
    assert "scope_permitted_claims_invalid" in m.validate_trust_evaluation(x)["issues"]

def test_validity_window_and_renewal_are_required():
    x=good(); x["validity"]["valid_until"]="2026-11-23T11:30:00Z"
    assert "evaluation_outside_validity_window" in m.validate_trust_evaluation(x)["issues"]
    x=good(); x["validity"]["renewal_required"]=False
    assert "renewal_must_be_required" in m.validate_trust_evaluation(x)["issues"]

def test_declared_decisions_are_enumerated_and_no_auto_trust():
    x=good(); x["decision"]="TRUSTED"
    assert "decision_invalid" in m.validate_trust_evaluation(x)["issues"]
    x=good(); x["automatic_trust"]=True
    assert "automatic_trust_must_be_false" in m.validate_trust_evaluation(x)["issues"]

def test_accepted_decision_requires_resolved_exceptions():
    x=good(); x["exceptions"][0]["resolution_evidence_ref"]=""
    assert "exception_resolution_evidence_missing" in m.validate_trust_evaluation(x)["issues"]
