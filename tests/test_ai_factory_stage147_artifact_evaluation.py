import hashlib

import pytest

from core.ai_factory_stage141_evolution import Fitness
from core.ai_factory_stage146_merge_strategy import MergeMethod, MergeReadiness, MergeRecipe
from core.ai_factory_stage147_artifact_evaluation import (
    ArtifactManifest, ArtifactPreflightError, MergeEvaluation, MergeEvaluationError,
    evaluate_merge_candidate, preflight_merge_inputs, verify_local_artifact,
)

SUITE = "e" * 64


def manifest(model_id, content, *, digest=None, path=None, fmt="safetensors", quant="fp16"):
    return ArtifactManifest(
        model_id=model_id,
        artifact_digest=digest or hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
        artifact_format=fmt,
        architecture="transformer-x",
        tokenizer_fingerprint="tok-v1",
        tensor_schema_fingerprint="schema-v1",
        quantization=quant,
        license_id="reviewed-license",
        provenance="signed-local-source",
        local_relative_path=path or f"models/{model_id}/weights.bin",
    )


def recipe():
    parents = (manifest("p-a", b"parent-a"), manifest("p-b", b"parent-b"))
    return MergeRecipe(
        candidate_id="child-147", generation=3, method=MergeMethod.SLERP,
        readiness=MergeReadiness.PROPOSAL_ONLY,
        parent_ids=("p-a", "p-b"),
        parent_artifact_digests=tuple(item.artifact_digest for item in parents),
        output_artifact_digest="f" * 64, tokenizer_fingerprint="tok-v1",
        tensor_schema_fingerprint="schema-v1", artifact_format="safetensors",
        quantization="fp16", coefficients=(.5, .5), density=None, seed=7,
        reasons=("fixture",), evidence_suite_digest=SUITE,
    ), parents


def metrics(accuracy, *, instruction=.92, safety=.99, latency=100, memory=800, regressions=0):
    return Fitness(accuracy, instruction, safety, latency, memory, regressions, SUITE)


def evaluation(model_id, digest, fitness, evaluator="independent-lab", evaluator_model="judge-1"):
    return MergeEvaluation(model_id, digest, SUITE, evaluator, evaluator_model, fitness)


def test_local_artifact_bytes_are_stream_verified_and_manifest_bound():
    item = manifest("local-a", b"123456789")
    verified = verify_local_artifact(item, (b"123", b"456", b"789"))
    assert verified.artifact_digest == item.artifact_digest
    assert verified.byte_length == 9
    assert len(verified.manifest_digest) == 64


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.bin", "models/../../secret", "C:\\weights.bin"])
def test_artifact_paths_reject_absolute_and_traversal(path):
    item = manifest("bad", b"abc", path=path)
    with pytest.raises(ArtifactPreflightError, match="relative path"):
        verify_local_artifact(item, (b"abc",))


def test_artifact_digest_and_length_must_match_actual_bytes():
    item = manifest("bad-digest", b"correct", digest="0" * 64)
    with pytest.raises(ArtifactPreflightError, match="digest"):
        verify_local_artifact(item, (b"correct",))
    item = manifest("bad-length", b"correct")
    with pytest.raises(ArtifactPreflightError, match="byte length"):
        verify_local_artifact(item, (b"wrong",))


def test_preflight_binds_exact_parent_digests_and_manifest_proofs():
    plan, parents = recipe()
    proofs = tuple(verify_local_artifact(item, (b"parent-a" if item.model_id == "p-a" else b"parent-b",))
                   for item in parents)
    report = preflight_merge_inputs(plan, parents, proofs)
    assert report.ready_for_separate_merge_approval is True
    assert report.candidate_id == plan.candidate_id
    assert len(report.recipe_digest) == 64


def test_preflight_rejects_parent_manifest_mismatch():
    plan, parents = recipe()
    proofs = tuple(verify_local_artifact(item, (b"parent-a" if item.model_id == "p-a" else b"parent-b",))
                   for item in parents)
    altered = (parents[0], manifest("p-b", b"tampered"))
    with pytest.raises(ArtifactPreflightError, match="digest"):
        preflight_merge_inputs(plan, altered, proofs)


def test_preflight_rejects_quantization_or_license_mismatch():
    plan, parents = recipe()
    proofs = tuple(verify_local_artifact(item, (b"parent-a" if item.model_id == "p-a" else b"parent-b",))
                   for item in parents)
    incompatible = (parents[0], manifest("p-b", b"parent-b", quant="q4_k_m"))
    incompatible_proofs = (
        proofs[0],
        verify_local_artifact(incompatible[1], (b"parent-b",)),
    )
    with pytest.raises(ArtifactPreflightError, match="incompatible"):
        preflight_merge_inputs(plan, incompatible, incompatible_proofs)
    license_mismatch = (
        parents[0],
        ArtifactManifest(
            **{**incompatible[1].__dict__, "license_id": "different-license"}
        ),
    )
    license_proofs = (
        proofs[0],
        verify_local_artifact(license_mismatch[1], (b"parent-b",)),
    )
    with pytest.raises(ArtifactPreflightError, match="incompatible"):
        preflight_merge_inputs(plan, license_mismatch, license_proofs)


def test_independent_before_after_evaluation_accepts_improved_candidate():
    plan, parents = recipe()
    baselines = (
        evaluation("p-a", parents[0].artifact_digest, metrics(.80)),
        evaluation("p-b", parents[1].artifact_digest, metrics(.82)),
    )
    candidate = evaluation("child-147", "a" * 64, metrics(.86, latency=95, memory=780))
    report = evaluate_merge_candidate(plan, baselines, candidate, builder_model_id="builder-1")
    assert report.decision == "IMPROVED"
    assert report.candidate_dominates_parent_count >= 1


def test_evaluation_rejects_suite_or_evaluator_drift():
    plan, parents = recipe()
    baselines = (
        evaluation("p-a", parents[0].artifact_digest, metrics(.80)),
        evaluation("p-b", parents[1].artifact_digest, metrics(.82)),
    )
    changed = MergeEvaluation("child-147", "a" * 64, "d" * 64, "independent-lab",
                              "judge-1", metrics(.86))
    with pytest.raises(MergeEvaluationError, match="suite"):
        evaluate_merge_candidate(plan, baselines, changed, builder_model_id="builder-1")
    changed = evaluation("child-147", "a" * 64, metrics(.86), evaluator="different-lab")
    with pytest.raises(MergeEvaluationError, match="evaluator identity"):
        evaluate_merge_candidate(plan, baselines, changed, builder_model_id="builder-1")


def test_evaluator_cannot_be_parent_or_builder():
    plan, parents = recipe()
    baselines = (
        evaluation("p-a", parents[0].artifact_digest, metrics(.80), evaluator_model="p-a"),
        evaluation("p-b", parents[1].artifact_digest, metrics(.82), evaluator_model="p-a"),
    )
    candidate = evaluation("child-147", "a" * 64, metrics(.86))
    with pytest.raises(MergeEvaluationError, match="not independent"):
        evaluate_merge_candidate(plan, baselines, candidate, builder_model_id="builder-1")
    baselines = (
        evaluation("p-a", parents[0].artifact_digest, metrics(.80)),
        evaluation("p-b", parents[1].artifact_digest, metrics(.82)),
    )
    candidate = evaluation("child-147", "a" * 64, metrics(.86), evaluator_model="builder-1")
    with pytest.raises(MergeEvaluationError, match="independent"):
        evaluate_merge_candidate(plan, baselines, candidate, builder_model_id="builder-1")


def test_candidate_must_be_new_artifact_and_pass_absolute_safety_gate():
    plan, parents = recipe()
    baselines = (
        evaluation("p-a", parents[0].artifact_digest, metrics(.80)),
        evaluation("p-b", parents[1].artifact_digest, metrics(.82)),
    )
    same_parent = evaluation("child-147", parents[0].artifact_digest, metrics(.86))
    with pytest.raises(MergeEvaluationError, match="new artifact"):
        evaluate_merge_candidate(plan, baselines, same_parent, builder_model_id="builder-1")
    unsafe = evaluation("child-147", "a" * 64, metrics(.90, safety=.90))
    report = evaluate_merge_candidate(plan, baselines, unsafe, builder_model_id="builder-1")
    assert report.decision == "BLOCKED"


def test_no_improvement_does_not_pass_evaluation_gate():
    plan, parents = recipe()
    baselines = (
        evaluation("p-a", parents[0].artifact_digest, metrics(.80)),
        evaluation("p-b", parents[1].artifact_digest, metrics(.82)),
    )
    candidate = evaluation("child-147", "a" * 64, metrics(.79))
    report = evaluate_merge_candidate(plan, baselines, candidate, builder_model_id="builder-1")
    assert report.decision == "NO_IMPROVEMENT"
