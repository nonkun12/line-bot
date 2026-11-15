import hashlib
import hmac

import pytest

from core.ai_factory_stage141_evolution import (
    CandidateStatus, CompatibilityReport, Fitness, MergeStrategy, ModelCandidate,
)
from core.ai_factory_stage142_lineage import EvaluationEvidence, evidence_digest
from core.ai_factory_stage143_evidence_auth import (
    AuthenticatedEvidenceVerifier, TrustedEvaluatorKey, signature_message,
)
from core.ai_factory_stage145_improvement_gate import (
    EvolutionDecision, GenerationImprovementReport, ParentComparison, SignedEvidence,
)
from core.ai_factory_stage146_merge_strategy import MergeMethod, MergeReadiness, MergeRecipe
from core.ai_factory_stage149_evolutionary_selection import (
    EvolutionPopulation, EvolutionPopulationError,
)


KEY_ID = "eval-key"
SECRET = b"x" * 32
SUITE = "a" * 64
ARTIFACT = "b" * 64


def fixture():
    verifier = AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)})
    fitness = Fitness(0.91, 0.93, 0.99, 100.0, 512.0, 0, SUITE)
    candidate = ModelCandidate(
        "child-1", ("parent-a", "parent-b"), MergeStrategy.SLERP,
        CompatibilityReport(True, MergeStrategy.SLERP, ()),
        fitness, 2, CandidateStatus.PENDING_HUMAN_APPROVAL, False,
    )
    evidence = EvaluationEvidence(
        candidate_id="child-1", evaluated_artifact_digest=ARTIFACT,
        evaluation_suite_digest=SUITE, evaluator_id="independent-evaluator",
        fitness=fitness, passed=True, evidence_digest="",
    )
    evidence = EvaluationEvidence(
        candidate_id=evidence.candidate_id,
        evaluated_artifact_digest=evidence.evaluated_artifact_digest,
        evaluation_suite_digest=evidence.evaluation_suite_digest,
        evaluator_id=evidence.evaluator_id, fitness=evidence.fitness, passed=True,
        evidence_digest=evidence_digest(
            candidate_id=evidence.candidate_id,
            evaluated_artifact_digest=evidence.evaluated_artifact_digest,
            evaluation_suite_digest=evidence.evaluation_suite_digest,
            evaluator_id=evidence.evaluator_id, fitness=evidence.fitness,
        ),
    )
    nonce = "nonce-1"
    signature = hmac.new(SECRET, signature_message(key_id=KEY_ID, nonce=nonce, evidence=evidence), hashlib.sha256).hexdigest()
    signed = SignedEvidence(evidence, KEY_ID, nonce, signature)
    comparisons = (
        ParentComparison("parent-a", 1, True, .02, .02, .01, .95, .95, 0),
        ParentComparison("parent-b", 1, False, .01, .01, .005, .98, .98, 0),
    )
    report = GenerationImprovementReport(
        "child-1", 2, EvolutionDecision.IMPROVED, comparisons,
        object(), "authenticated improvement",
    )
    recipe = MergeRecipe(
        candidate_id="child-1", generation=2, method=MergeMethod.SLERP,
        readiness=MergeReadiness.PROPOSAL_ONLY,
        parent_ids=("parent-a", "parent-b"),
        parent_artifact_digests=("c" * 64, "d" * 64),
        output_artifact_digest=ARTIFACT, tokenizer_fingerprint="tok",
        tensor_schema_fingerprint="schema", artifact_format="safetensors",
        quantization="fp16", coefficients=(.5, .5), density=None, seed=7,
        reasons=("compatible fixture",), evidence_suite_digest=SUITE,
    )
    return verifier, candidate, report, recipe, signed


def test_admission_reverifies_signed_evidence_and_plans_next_generation():
    _, candidate, report, recipe, signed = fixture()
    population = EvolutionaryPopulation(
        AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)}),
        max_population=4, max_survivors=2,
    )
    entry = population.admit(candidate, report, recipe, signed, expected_artifact_digest=ARTIFACT)
    assert entry.candidate_id == "child-1"
    assert entry.status == "pending_human_approval"
    assert entry.enabled is False
    snapshot = population.snapshot()
    assert snapshot.pareto_frontier == ("child-1",)
    plan = population.plan_next_generation()
    assert plan.source_generation == 2
    assert plan.next_generation == 3
    assert plan.survivor_candidate_ids == ("child-1",)
    assert plan.auto_advance is False
    assert plan.merge_authorized is False
    assert plan.activation_authorized is False
    assert plan.production_switch_authorized is False


@pytest.mark.parametrize("kwargs", [
    {"kill_switch_active": True},
    {"hold_active": True},
    {"budget_available": False},
])
def test_safety_stops_fail_closed(kwargs):
    _, candidate, report, recipe, signed = fixture()
    population = EvolutionaryPopulation(
        AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)})
    )
    with pytest.raises(EvolutionPopulationError):
        population.admit(candidate, report, recipe, signed, expected_artifact_digest=ARTIFACT, **kwargs)


def test_rejects_report_or_recipe_identity_drift():
    _, candidate, report, recipe, signed = fixture()
    population = EvolutionaryPopulation(
        AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)})
    )
    bad_report = GenerationImprovementReport(
        "other", 2, EvolutionDecision.IMPROVED, report.comparisons, object(), "forged"
    )
    with pytest.raises(EvolutionPopulationError):
        population.admit(candidate, bad_report, recipe, signed, expected_artifact_digest=ARTIFACT)


def test_rejects_tampered_signature_and_artifact_digest():
    _, candidate, report, recipe, signed = fixture()
    population = EvolutionaryPopulation(
        AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)})
    )
    tampered = SignedEvidence(signed.evidence, signed.key_id, signed.nonce, "0" * 64)
    with pytest.raises(EvolutionPopulationError):
        population.admit(candidate, report, recipe, tampered, expected_artifact_digest=ARTIFACT)


def test_capacity_is_bounded_and_fail_closed():
    _, candidate, report, recipe, signed = fixture()
    population = EvolutionaryPopulation(
        AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)}),
        max_population=1,
    )
    population.admit(candidate, report, recipe, signed, expected_artifact_digest=ARTIFACT)
    assert len(population.snapshot().entries) == 1
    assert population.snapshot().capacity == 1


def test_candidate_must_be_pending_and_disabled():
    _, candidate, report, recipe, signed = fixture()
    active = ModelCandidate(
        candidate.candidate_id, candidate.parent_ids, candidate.strategy,
        candidate.compatibility, candidate.fitness, candidate.generation,
        CandidateStatus.PENDING_HUMAN_APPROVAL, True,
    )
    population = EvolutionaryPopulation(
        AuthenticatedEvidenceVerifier({KEY_ID: TrustedEvaluatorKey("independent-evaluator", SECRET)})
    )
    with pytest.raises(EvolutionPopulationError):
        population.admit(active, report, recipe, signed, expected_artifact_digest=ARTIFACT)
