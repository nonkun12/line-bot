import pytest

from core.ai_factory_stage141_evolution import (
    EvolutionaryModelMergePlanner, Fitness, ModelDescriptor,
)
from core.ai_factory_stage142_lineage import (
    EvaluationEvidenceAdapter, ModelLineageRegistry, evidence_digest,
)


def model(name):
    return ModelDescriptor(
        model_id=name,
        architecture="local-transformer",
        tokenizer_fingerprint="tokenizer-sha",
        tensor_schema_fingerprint="tensor-schema-sha",
        artifact_format="safetensors",
        artifact_digest=("a" if name == "parent-a" else "b") * 64,
        license_id="license-reviewed",
        provenance="local-manifest",
        local_artifact_available=True,
    )


def make_candidate(*, generation=1):
    parents = (model("parent-a"), model("parent-b"))
    fitness = Fitness(
        accuracy=.94, instruction_following=.93, safety=.99,
        latency_ms=120, memory_mb=900, regression_count=0,
        evaluation_suite_digest="e" * 64,
    )
    report = EvolutionaryModelMergePlanner().plan(
        "stage142-tick", (parents,), (fitness,), generation=generation,
    )
    assert len(report.candidates) == 1
    return parents, report.candidates[0], fitness


def make_evidence(candidate, fitness, *, evaluator="independent-evaluator", passed=True):
    artifact = "c" * 64
    digest = evidence_digest(
        candidate_id=candidate.candidate_id,
        evaluated_artifact_digest=artifact,
        evaluation_suite_digest=fitness.evaluation_suite_digest,
        evaluator_id=evaluator,
        fitness=fitness,
    )
    return {
        "candidate_id": candidate.candidate_id,
        "evaluated_artifact_digest": artifact,
        "evaluation_suite_digest": fitness.evaluation_suite_digest,
        "evaluator_id": evaluator,
        "accuracy": fitness.accuracy,
        "instruction_following": fitness.instruction_following,
        "safety": fitness.safety,
        "latency_ms": fitness.latency_ms,
        "memory_mb": fitness.memory_mb,
        "regression_count": fitness.regression_count,
        "passed": passed,
    }, digest


def test_adapter_ingests_exact_schema_and_binds_evidence_digest():
    parents, candidate, fitness = make_candidate()
    payload, digest = make_evidence(candidate, fitness)
    evidence = EvaluationEvidenceAdapter().ingest(payload)
    assert evidence.evidence_digest == digest
    record = ModelLineageRegistry().record(candidate, parents, evidence)
    assert record.parent_ids == ("parent-a", "parent-b")
    assert record.generation == 1
    assert record.enabled is False


def test_adapter_rejects_extra_or_missing_fields():
    parents, candidate, fitness = make_candidate()
    payload, _ = make_evidence(candidate, fitness)
    with pytest.raises(ValueError, match="exact evidence schema"):
        EvaluationEvidenceAdapter().ingest({**payload, "approved": True})
    payload.pop("passed")
    with pytest.raises(ValueError, match="exact evidence schema"):
        EvaluationEvidenceAdapter().ingest(payload)


def test_registry_rejects_failed_or_non_independent_evaluation():
    parents, candidate, fitness = make_candidate()
    payload, _ = make_evidence(candidate, fitness, passed=False)
    evidence = EvaluationEvidenceAdapter().ingest(payload)
    with pytest.raises(PermissionError, match="did not pass"):
        ModelLineageRegistry().record(candidate, parents, evidence)

    payload, _ = make_evidence(candidate, fitness, evaluator="parent-a")
    evidence = EvaluationEvidenceAdapter().ingest(payload)
    with pytest.raises(PermissionError, match="independent"):
        ModelLineageRegistry().record(candidate, parents, evidence)


def test_registry_rejects_wrong_candidate_parent_and_generation():
    parents, candidate, fitness = make_candidate(generation=2)
    payload, _ = make_evidence(candidate, fitness)
    evidence = EvaluationEvidenceAdapter().ingest(payload)
    with pytest.raises(ValueError, match="generation"):
        ModelLineageRegistry().record(candidate, parents, evidence)

    payload, _ = make_evidence(candidate, fitness)
    evidence = EvaluationEvidenceAdapter().ingest(payload)
    with pytest.raises(ValueError, match="parent descriptors"):
        ModelLineageRegistry().record(candidate, (model("parent-a"), model("other")), evidence)


def test_registry_is_idempotent_immutable_and_capacity_bounded():
    parents, candidate, fitness = make_candidate()
    payload, _ = make_evidence(candidate, fitness)
    evidence = EvaluationEvidenceAdapter().ingest(payload)
    registry = ModelLineageRegistry(max_records=1)
    first = registry.record(candidate, parents, evidence)
    second = registry.record(candidate, parents, evidence)
    assert first == second
    assert registry.count() == 1
    assert registry.get(candidate.candidate_id) == first
    assert registry.list_records() == (first,)
    with pytest.raises((AttributeError, TypeError)):
        first.enabled = True


def test_evidence_adapter_rejects_digest_shape_and_bad_metrics():
    parents, candidate, fitness = make_candidate()
    payload, _ = make_evidence(candidate, fitness)
    payload["evaluated_artifact_digest"] = "not-a-digest"
    with pytest.raises(ValueError, match="SHA-256"):
        EvaluationEvidenceAdapter().ingest(payload)
    payload, _ = make_evidence(candidate, fitness)
    payload["accuracy"] = float("nan")
    with pytest.raises(ValueError, match="invalid metric"):
        EvaluationEvidenceAdapter().ingest(payload)
