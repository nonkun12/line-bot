from dataclasses import replace
import hashlib
import pytest

from core.ai_factory_stage176_180_merge_readiness import (
    MergeReadinessError, Stage176ArtifactManifestBuilder, ReproducibilityEvidence,
    Stage177ReproducibilityVerifier, ResourceEnvelope, Stage178ResourceGate,
    HoldoutEvidence, Stage179HoldoutGate, Stage180HumanApprovalPackager,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def manifest():
    return Stage176ArtifactManifestBuilder().build(
        candidate_id="candidate-1", candidate_artifact_digest=digest("candidate"),
        parent_artifact_digests=(digest("parent-a"), digest("parent-b")),
        evaluation_suite_digest=digest("suite"), selection_digest=digest("selection"),
        source_generation=7, proposed_generation=8,
    )


def repro_evidence(m, executor, evaluator, rerun, output="same-output"):
    return ReproducibilityEvidence(m.manifest_digest, m.candidate_artifact_digest,
        m.evaluation_suite_digest, executor, evaluator, rerun, digest(output), "signed")


def test_stage176_creates_immutable_adjacent_generation_manifest():
    m = manifest()
    assert m.immutable and m.proposal_only
    assert m.proposed_generation == m.source_generation + 1
    assert len(m.manifest_digest) == 64


@pytest.mark.parametrize("kwargs", [
    {"candidate_artifact_digest": "bad"},
    {"parent_artifact_digests": ("a" * 64,)},
    {"proposed_generation": 9},
])
def test_stage176_rejects_invalid_manifest_inputs(kwargs):
    args = dict(candidate_id="candidate-1", candidate_artifact_digest=digest("candidate"),
        parent_artifact_digests=(digest("a"), digest("b")),
        evaluation_suite_digest=digest("suite"), selection_digest=digest("selection"),
        source_generation=7, proposed_generation=8)
    args.update(kwargs)
    with pytest.raises(MergeReadinessError):
        Stage176ArtifactManifestBuilder().build(**args)


def test_stage177_requires_distinct_signed_reproducible_reruns():
    m = manifest()
    rows = [repro_evidence(m, "exec-a", "eval-a", "run-a"),
            repro_evidence(m, "exec-b", "eval-b", "run-b")]
    report = Stage177ReproducibilityVerifier().build(m, rows, verify_signature=lambda x: True)
    assert report.reproducible and report.rerun_count == 2
    assert report.proposal_only


def test_stage177_rejects_drift_replay_and_non_reproducible_output():
    m = manifest()
    verifier = Stage177ReproducibilityVerifier()
    rows = [repro_evidence(m, "exec-a", "eval-a", "run-a"),
            repro_evidence(m, "exec-b", "eval-b", "run-b", "different")]
    assert not verifier.build(m, rows, verify_signature=lambda x: True).reproducible
    with pytest.raises(MergeReadinessError, match="replayed"):
        verifier.build(m, [rows[0], rows[0]], verify_signature=lambda x: True)
    with pytest.raises(MergeReadinessError, match="signature"):
        verifier.build(m, rows, verify_signature=lambda x: False)


def test_stage178_enforces_local_free_resource_envelope():
    gate = Stage178ResourceGate()
    ok = gate.assess(ResourceEnvelope(4096, 10000, 30, 8192, 20000, 60))
    assert ok.feasible and ok.proposal_only
    bad = gate.assess(ResourceEnvelope(9000, 10000, 30, 8192, 20000, 60))
    assert not bad.feasible and "RAM budget exceeded" in bad.reasons
    cloud = gate.assess(ResourceEnvelope(100, 100, 1, 200, 200, 2, execution_location="cloud"))
    assert not cloud.feasible


def test_stage179_requires_separate_signed_holdout_with_zero_critical_failures():
    m = manifest()
    evidence = HoldoutEvidence(m.manifest_digest, digest("holdout-suite"), "holdout-evaluator",
                               digest("report"), 100, 99, 0, "signed")
    assessment = Stage179HoldoutGate().assess(m, evidence, verify_signature=lambda x: True)
    assert assessment.passed and assessment.pass_rate == .99
    bad = replace(evidence, critical_failures=1)
    assert not Stage179HoldoutGate().assess(m, bad, verify_signature=lambda x: True).passed
    with pytest.raises(MergeReadinessError, match="separate"):
        Stage179HoldoutGate().assess(m, replace(evidence, holdout_suite_digest=m.evaluation_suite_digest),
                                     verify_signature=lambda x: True)


def test_stage180_builds_human_review_package_without_authorizing_execution():
    m = manifest()
    repro = Stage177ReproducibilityVerifier().build(
        m, [repro_evidence(m, "exec-a", "eval-a", "run-a"),
            repro_evidence(m, "exec-b", "eval-b", "run-b")], verify_signature=lambda x: True)
    resources = Stage178ResourceGate().assess(ResourceEnvelope(100, 200, 2, 500, 1000, 10))
    holdout = Stage179HoldoutGate().assess(m, HoldoutEvidence(
        m.manifest_digest, digest("holdout-suite"), "holdout-evaluator",
        digest("report"), 100, 100, 0, "signed"), verify_signature=lambda x: True)
    package = Stage180HumanApprovalPackager().build(
        m, repro, resources, holdout, rollback_artifact_digest=digest("rollback"))
    assert package.ready_for_human_review and package.human_approval_required
    assert not package.human_approval_granted
    assert not package.merge_execution_authorized
    assert not package.weight_mutation_authorized
    assert not package.generation_advance_authorized
    assert not package.model_activation_authorized
    assert not package.production_switch_authorized


@pytest.mark.parametrize("stage", [176, 177, 178, 179, 180])
def test_hold_blocks_each_stage(stage):
    m = manifest()
    with pytest.raises(MergeReadinessError, match="HOLD"):
        if stage == 176:
            Stage176ArtifactManifestBuilder().build(candidate_id="c", candidate_artifact_digest=digest("c"),
                parent_artifact_digests=(digest("a"), digest("b")), evaluation_suite_digest=digest("s"),
                selection_digest=digest("x"), source_generation=1, proposed_generation=2, hold_active=True)
        elif stage == 177:
            Stage177ReproducibilityVerifier().build(m, [], verify_signature=lambda x: True, hold_active=True)
        elif stage == 178:
            Stage178ResourceGate().assess(ResourceEnvelope(1, 1, 1, 2, 2, 2), hold_active=True)
        elif stage == 179:
            Stage179HoldoutGate().assess(m, HoldoutEvidence(m.manifest_digest, digest("h"), "e",
                digest("r"), 20, 20, 0, "sig"), verify_signature=lambda x: True, hold_active=True)
        else:
            Stage180HumanApprovalPackager().build(m, None, None, None,
                rollback_artifact_digest=digest("rollback"), hold_active=True)
