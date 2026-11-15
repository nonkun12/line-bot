import hashlib
import hmac

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage142_lineage import EvaluationEvidence, evidence_digest
from core.ai_factory_stage143_evidence_auth import (
    AuthenticatedEvidenceVerifier,
    EvidenceVerificationError,
    TrustedEvaluatorKey,
    signature_message,
)


def make_evidence():
    fitness = Fitness(
        accuracy=.96, instruction_following=.95, safety=.99,
        latency_ms=100, memory_mb=800, regression_count=0,
        evaluation_suite_digest="e" * 64,
    )
    artifact = "a" * 64
    evaluator = "trusted-lab"
    candidate = "candidate-143"
    digest = evidence_digest(
        candidate_id=candidate,
        evaluated_artifact_digest=artifact,
        evaluation_suite_digest=fitness.evaluation_suite_digest,
        evaluator_id=evaluator,
        fitness=fitness,
    )
    return EvaluationEvidence(
        candidate_id=candidate,
        evaluated_artifact_digest=artifact,
        evaluation_suite_digest=fitness.evaluation_suite_digest,
        evaluator_id=evaluator,
        fitness=fitness,
        passed=True,
        evidence_digest=digest,
    )


def signed(evidence, *, nonce="nonce-1", key_id="lab-key", secret=b"x" * 32):
    message = signature_message(key_id=key_id, nonce=nonce, evidence=evidence)
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verifier(*, max_nonces=10):
    return AuthenticatedEvidenceVerifier(
        {"lab-key": TrustedEvaluatorKey("trusted-lab", b"x" * 32)},
        max_nonces=max_nonces,
    )


def verify(v, evidence, *, nonce="nonce-1", signature=None, **overrides):
    args = {
        "key_id": "lab-key",
        "nonce": nonce,
        "signature_hex": signature or signed(evidence, nonce=nonce),
        "expected_candidate_id": evidence.candidate_id,
        "expected_artifact_digest": evidence.evaluated_artifact_digest,
        "expected_suite_digest": evidence.evaluation_suite_digest,
    }
    args.update(overrides)
    return v.verify(evidence, **args)


def test_valid_trusted_signature_is_accepted_once():
    evidence = make_evidence()
    assert verify(verifier(), evidence) == evidence


def test_unknown_key_and_evaluator_identity_mismatch_are_rejected():
    evidence = make_evidence()
    v = verifier()
    with pytest.raises(EvidenceVerificationError, match="unknown key"):
        verify(v, evidence, key_id="unknown")
    with pytest.raises(EvidenceVerificationError, match="identity mismatch"):
        AuthenticatedEvidenceVerifier(
            {"lab-key": TrustedEvaluatorKey("different-lab", b"x" * 32)}
        ).verify(
            evidence, key_id="lab-key", nonce="n", signature_hex=signed(evidence, nonce="n"),
            expected_candidate_id=evidence.candidate_id,
            expected_artifact_digest=evidence.evaluated_artifact_digest,
            expected_suite_digest=evidence.evaluation_suite_digest,
        )


def test_tampered_signature_and_wrong_candidate_artifact_or_suite_fail():
    evidence = make_evidence()
    with pytest.raises(EvidenceVerificationError, match="signature"):
        verify(verifier(), evidence, signature="0" * 64)
    for field, value in (
        ("expected_candidate_id", "other"),
        ("expected_artifact_digest", "b" * 64),
        ("expected_suite_digest", "c" * 64),
    ):
        with pytest.raises(EvidenceVerificationError, match="mismatch"):
            verify(verifier(), evidence, nonce=field, **{field: value})


def test_replay_and_capacity_are_fail_closed():
    evidence = make_evidence()
    v = verifier(max_nonces=1)
    verify(v, evidence)
    with pytest.raises(EvidenceVerificationError, match="already used"):
        verify(v, evidence)
    with pytest.raises(EvidenceVerificationError, match="capacity"):
        verify(v, evidence, nonce="nonce-2")


def test_bad_trust_key_and_nonce_are_rejected():
    with pytest.raises(ValueError, match="32 bytes"):
        TrustedEvaluatorKey("lab", b"short")
    evidence = make_evidence()
    with pytest.raises(EvidenceVerificationError, match="canonicalization"):
        verify(verifier(), evidence, nonce="bad nonce", signature="0" * 64)


def test_digest_tampering_is_rejected_before_signature_check():
    evidence = make_evidence()
    forged = EvaluationEvidence(
        candidate_id=evidence.candidate_id,
        evaluated_artifact_digest=evidence.evaluated_artifact_digest,
        evaluation_suite_digest=evidence.evaluation_suite_digest,
        evaluator_id=evidence.evaluator_id,
        fitness=evidence.fitness,
        passed=True,
        evidence_digest="f" * 64,
    )
    with pytest.raises(EvidenceVerificationError, match="canonicalization"):
        verify(verifier(), forged, signature="0" * 64)
