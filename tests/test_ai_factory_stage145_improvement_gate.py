import hashlib
import hmac

import pytest

from core.ai_factory_stage141_evolution import (
    CandidateStatus, CompatibilityReport, Fitness, MergeStrategy, ModelCandidate, ModelDescriptor,
)
from core.ai_factory_stage142_lineage import EvaluationEvidence, evidence_digest
from core.ai_factory_stage143_evidence_auth import (
    AuthenticatedEvidenceVerifier, TrustedEvaluatorKey, signature_message,
)
from core.ai_factory_stage144_evolution_selection import AuthenticatedEvolutionEvidenceStore
from core.ai_factory_stage145_improvement_gate import (
    EvolutionDecision, GenerationImprovementGate, ParentEvaluation, SignedEvidence,
)

SECRET = b"stage145-test-secret-material-32bytes"
SUITE = "e" * 64


def model(name):
    return ModelDescriptor(
        model_id=name, architecture="transformer-x", tokenizer_fingerprint="tok",
        tensor_schema_fingerprint="tensor", artifact_format="safetensors",
        artifact_digest=hashlib.sha256(name.encode()).hexdigest(),
        license_id="reviewed", provenance="local-test", local_artifact_available=True,
    )


def fitness(accuracy, instruction=.90, safety=.99, latency=100, memory=800, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


def signed_evidence(identity, artifact, metrics, nonce):
    evaluator = "independent-lab"
    digest = evidence_digest(
        candidate_id=identity, evaluated_artifact_digest=artifact,
        evaluation_suite_digest=metrics.evaluation_suite_digest, evaluator_id=evaluator, fitness=metrics,
    )
    evidence = EvaluationEvidence(identity, artifact, metrics.evaluation_suite_digest, evaluator, metrics, True, digest)
    key_id = "lab-key"
    signature = hmac.new(
        SECRET, signature_message(key_id=key_id, nonce=nonce, evidence=evidence),
        hashlib.sha256,
    ).hexdigest()
    return SignedEvidence(evidence, key_id, nonce, signature)


def setup(candidate_metrics=None, *, parent_metrics=None, generation=2):
    verifier = AuthenticatedEvidenceVerifier(
        {"lab-key": TrustedEvaluatorKey("independent-lab", SECRET)}
    )
    store = AuthenticatedEvolutionEvidenceStore(verifier, max_candidates=8)
    parent_metrics = parent_metrics or {"parent-a": fitness(.80), "parent-b": fitness(.82)}
    parents = tuple(
        ParentEvaluation(model(name), 1, signed_evidence(name, model(name).artifact_digest, metric, f"p-{name}"))
        for name, metric in parent_metrics.items()
    )
    child_metrics = candidate_metrics or fitness(.86, instruction=.93, latency=95, memory=780)
    candidate = ModelCandidate(
        "child-145", tuple(item.descriptor.model_id for item in parents),
        MergeStrategy.PARAMETER, CompatibilityReport(True, MergeStrategy.PARAMETER, ("fixture",)),
        child_metrics, generation, CandidateStatus.PENDING_HUMAN_APPROVAL, False,
    )
    child_artifact = "c" * 64
    child_signed = signed_evidence(candidate.candidate_id, child_artifact, child_metrics, "child-nonce")
    gate = GenerationImprovementGate(verifier, store)
    return gate, store, candidate, parents, child_signed, child_artifact


def test_improved_child_requires_signed_parent_and_child_evidence():
    gate, store, candidate, parents, child, artifact = setup()
    report = gate.evaluate(candidate, parents, child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.IMPROVED
    assert report.lineage_record is not None
    assert store.count() == 1
    assert report.lineage_record.enabled is False


def test_no_improvement_is_not_admitted():
    gate, store, candidate, parents, child, artifact = setup(candidate_metrics=fitness(.81, instruction=.89))
    report = gate.evaluate(candidate, parents, child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.NO_IMPROVEMENT
    assert report.lineage_record is None
    assert store.count() == 0


def test_material_regression_blocks_candidate():
    gate, store, candidate, parents, child, artifact = setup(
        candidate_metrics=fitness(.70, instruction=.93, latency=95, memory=780)
    )
    report = gate.evaluate(candidate, parents, child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.BLOCKED
    assert "accuracy regression" in report.reason
    assert store.count() == 0


def test_suite_mismatch_in_parent_evidence_blocks():
    gate, store, candidate, parents, child, artifact = setup()
    altered = []
    for index, parent in enumerate(parents):
        bad = parent.signed_evidence
        if index == 0:
            metrics = Fitness(.80, .90, .99, 100, 800, 0, "f" * 64)
            bad = signed_evidence(parent.descriptor.model_id, parent.descriptor.artifact_digest, metrics, "wrong-suite")
        altered.append(ParentEvaluation(parent.descriptor, parent.generation, bad))
    report = gate.evaluate(candidate, tuple(altered), child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.BLOCKED
    assert "parent evidence rejected" in report.reason
    assert store.count() == 0


def test_parent_signature_tampering_blocks_candidate():
    gate, store, candidate, parents, child, artifact = setup()
    first = parents[0]
    tampered = SignedEvidence(first.signed_evidence.evidence, "lab-key", "tampered", "0" * 64)
    parents = (ParentEvaluation(first.descriptor, first.generation, tampered),) + parents[1:]
    report = gate.evaluate(candidate, parents, child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.BLOCKED
    assert "signature" in report.reason
    assert store.count() == 0


def test_generation_must_follow_newest_parent():
    gate, store, candidate, parents, child, artifact = setup(generation=1)
    report = gate.evaluate(candidate, parents, child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.BLOCKED
    assert "generation" in report.reason
    assert store.count() == 0


def test_candidate_artifact_identity_must_match_signed_evidence():
    gate, store, candidate, parents, child, artifact = setup()
    report = gate.evaluate(candidate, parents, child, expected_candidate_artifact_digest="d" * 64)
    assert report.decision is EvolutionDecision.BLOCKED
    assert "candidate evidence" in report.reason
    assert store.count() == 0


def test_disabled_pending_approval_is_mandatory():
    gate, store, candidate, parents, child, artifact = setup()
    enabled = ModelCandidate(
        candidate.candidate_id, candidate.parent_ids, candidate.strategy, candidate.compatibility,
        candidate.fitness, candidate.generation, candidate.status, True,
    )
    report = gate.evaluate(enabled, parents, child, expected_candidate_artifact_digest=artifact)
    assert report.decision is EvolutionDecision.BLOCKED
    assert store.count() == 0
