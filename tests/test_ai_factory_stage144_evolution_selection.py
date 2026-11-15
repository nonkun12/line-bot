import hashlib
import hmac

import pytest

from core.ai_factory_stage141_evolution import (
    CandidateStatus,
    CompatibilityReport,
    Fitness,
    MergeStrategy,
    ModelCandidate,
    ModelDescriptor,
)
from core.ai_factory_stage142_lineage import EvaluationEvidence, evidence_digest
from core.ai_factory_stage143_evidence_auth import (
    AuthenticatedEvidenceVerifier,
    TrustedEvaluatorKey,
    signature_message,
)
from core.ai_factory_stage144_evolution_selection import AuthenticatedEvolutionEvidenceStore


SECRET = b"stage144-test-secret-material-32bytes"


def make_parent(model_id):
    return ModelDescriptor(
        model_id=model_id,
        architecture="transformer-x",
        tokenizer_fingerprint="tok-v1",
        tensor_schema_fingerprint="tensor-v1",
        artifact_format="safetensors",
        artifact_digest=hashlib.sha256(model_id.encode()).hexdigest(),
        license_id="permissive-review-required",
        provenance="local-test-fixture",
        local_artifact_available=True,
    )


def make_candidate(candidate_id="cand-144", suite="e" * 64):
    fitness = Fitness(
        accuracy=.97, instruction_following=.96, safety=.99,
        latency_ms=90, memory_mb=700, regression_count=0,
        evaluation_suite_digest=suite,
    )
    compatibility = CompatibilityReport(
        True, MergeStrategy.PARAMETER, ("test fixture compatibility",)
    )
    return ModelCandidate(
        candidate_id=candidate_id,
        parent_ids=("parent-a", "parent-b"),
        strategy=MergeStrategy.PARAMETER,
        compatibility=compatibility,
        fitness=fitness,
        generation=1,
        status=CandidateStatus.PENDING_HUMAN_APPROVAL,
        enabled=False,
    )


def make_evidence(candidate):
    artifact = "a" * 64
    evaluator = "independent-evaluator"
    digest = evidence_digest(
        candidate_id=candidate.candidate_id,
        evaluated_artifact_digest=artifact,
        evaluation_suite_digest=candidate.fitness.evaluation_suite_digest,
        evaluator_id=evaluator,
        fitness=candidate.fitness,
    )
    return EvaluationEvidence(
        candidate_id=candidate.candidate_id,
        evaluated_artifact_digest=artifact,
        evaluation_suite_digest=candidate.fitness.evaluation_suite_digest,
        evaluator_id=evaluator,
        fitness=candidate.fitness,
        passed=True,
        evidence_digest=digest,
    )


def make_store(max_candidates=4):
    verifier = AuthenticatedEvidenceVerifier(
        {"lab-key": TrustedEvaluatorKey("independent-evaluator", SECRET)}
    )
    return AuthenticatedEvolutionEvidenceStore(verifier, max_candidates=max_candidates)


def signed(evidence, nonce):
    message = signature_message(key_id="lab-key", nonce=nonce, evidence=evidence)
    return hmac.new(SECRET, message, hashlib.sha256).hexdigest()


def accept(store, candidate, *, nonce="nonce-1"):
    evidence = make_evidence(candidate)
    return store.accept(
        candidate,
        (make_parent("parent-a"), make_parent("parent-b")),
        evidence,
        key_id="lab-key",
        nonce=nonce,
        signature_hex=signed(evidence, nonce),
        expected_artifact_digest=evidence.evaluated_artifact_digest,
        expected_suite_digest=evidence.evaluation_suite_digest,
    )


def test_only_authenticated_evidence_enters_selection_and_lineage():
    store = make_store()
    record = accept(store, make_candidate())
    snapshot = store.snapshot()
    assert record.candidate_id == "cand-144"
    assert snapshot.accepted_candidate_ids == ("cand-144",)
    assert snapshot.pareto_frontier_ids == ("cand-144",)
    assert snapshot.records == (record,)


def test_bad_signature_or_expected_artifact_does_not_enter_pool():
    store = make_store()
    candidate = make_candidate()
    evidence = make_evidence(candidate)
    with pytest.raises(PermissionError, match="signature"):
        store.accept(
            candidate, (make_parent("parent-a"), make_parent("parent-b")), evidence,
            key_id="lab-key", nonce="bad-signature", signature_hex="0" * 64,
            expected_artifact_digest=evidence.evaluated_artifact_digest,
            expected_suite_digest=evidence.evaluation_suite_digest,
        )
    assert store.count() == 0


def test_fitness_mismatch_and_duplicate_candidate_are_rejected():
    store = make_store()
    candidate = make_candidate()
    accept(store, candidate)
    with pytest.raises(ValueError, match="already accepted"):
        accept(store, candidate, nonce="second-nonce")


def test_failed_lineage_validation_consumes_nonce_and_adds_nothing():
    store = make_store()
    candidate = make_candidate()
    evidence = make_evidence(candidate)
    with pytest.raises(ValueError, match="parent descriptors"):
        store.accept(
            candidate, (make_parent("wrong-a"), make_parent("wrong-b")), evidence,
            key_id="lab-key", nonce="consumed", signature_hex=signed(evidence, "consumed"),
            expected_artifact_digest=evidence.evaluated_artifact_digest,
            expected_suite_digest=evidence.evaluation_suite_digest,
        )
    assert store.count() == 0
    with pytest.raises(PermissionError, match="already used"):
        store.accept(
            candidate, (make_parent("parent-a"), make_parent("parent-b")), evidence,
            key_id="lab-key", nonce="consumed", signature_hex=signed(evidence, "consumed"),
            expected_artifact_digest=evidence.evaluated_artifact_digest,
            expected_suite_digest=evidence.evaluation_suite_digest,
        )


def test_candidate_pool_capacity_is_bounded():
    store = make_store(max_candidates=1)
    accept(store, make_candidate("cand-one"), nonce="one")
    with pytest.raises(OverflowError, match="capacity"):
        accept(store, make_candidate("cand-two"), nonce="two")
    assert store.count() == 1


def test_candidate_must_remain_pending_and_disabled():
    store = make_store()
    candidate = make_candidate()
    enabled = ModelCandidate(
        candidate_id=candidate.candidate_id,
        parent_ids=candidate.parent_ids,
        strategy=candidate.strategy,
        compatibility=candidate.compatibility,
        fitness=candidate.fitness,
        generation=candidate.generation,
        status=candidate.status,
        enabled=True,
    )
    evidence = make_evidence(enabled)
    with pytest.raises(PermissionError, match="disabled pending"):
        store.accept(
            enabled, (make_parent("parent-a"), make_parent("parent-b")), evidence,
            key_id="lab-key", nonce="enabled", signature_hex=signed(evidence, "enabled"),
            expected_artifact_digest=evidence.evaluated_artifact_digest,
            expected_suite_digest=evidence.evaluation_suite_digest,
        )
    assert store.count() == 0
