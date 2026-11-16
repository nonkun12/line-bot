import hashlib
from dataclasses import replace

import pytest

from core.ai_factory_stage176_180_merge_readiness import (
    EvolutionaryReadinessError,
    HoldoutEvidence,
    ImmutableArtifactManifest,
    ReproducibilityRun,
    ResourceEnvelope,
    ResourceEstimate,
    SelectedMergeCandidate,
    Stage176ArtifactManifestBuilder,
    Stage177ReproducibilityVerifier,
    Stage178ResourceFeasibilityGate,
    Stage179HoldoutRobustnessGate,
    Stage180HumanApprovalPackager,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def candidate():
    return SelectedMergeCandidate(
        "candidate-a", "slerp", ("parent-a", "parent-b"),
        (digest("parent-a"), digest("parent-b")), digest("candidate-a"),
        digest("suite"), digest("selection"), 4, 5, "Apache-2.0",
    )


def manifest():
    return Stage176ArtifactManifestBuilder().build(candidate())


def reproducibility(m=None, *, result_values=None, passed=True):
    m = m or manifest()
    values = result_values or [digest("same-result"), digest("same-result")]
    runs = tuple(
        ReproducibilityRun(
            m.manifest_digest, m.candidate_artifact_digest,
            m.evaluation_suite_digest, f"runner-{i}", f"evaluator-{i}",
            f"run-{i}", value, passed, f"signed-{i}",
        )
        for i, value in enumerate(values)
    )
    return Stage177ReproducibilityVerifier().build(m, runs, verify_signature=lambda _: True)


def resource_report(m=None, rep=None, estimate=None, envelope=None):
    m = m or manifest()
    rep = rep or reproducibility(m)
    estimate = estimate or ResourceEstimate(1024, 2048, 120, 2.0, digest("estimate"))
    envelope = envelope or ResourceEnvelope(4096, 8192, 600, 4.0)
    return Stage178ResourceFeasibilityGate().assess(m, rep, estimate, envelope)


def holdout_report(m=None, *, safety=True, contamination=True, robustness=.98):
    m = m or manifest()
    evidence = tuple(
        HoldoutEvidence(
            m.manifest_digest, m.candidate_artifact_digest, digest("holdout-suite"),
            f"holdout-{i}", f"holdout-evaluator-{i}", safety, robustness,
            contamination, f"signed-holdout-{i}", digest(f"holdout-evidence-{i}"),
        )
        for i in range(2)
    )
    return Stage179HoldoutRobustnessGate().build(
        m, evidence, verify_signature=lambda _: True
    )


def test_stage176_manifest_binds_candidate_and_parent_lineage():
    m = manifest()
    assert m.immutable and m.proposal_only
    assert not m.artifact_write_authorized
    assert not m.model_merge_authorized and not m.weight_mutation_authorized
    assert not m.generation_advanced
    assert m.source_generation == 4 and m.proposed_generation == 5


def test_stage176_rejects_non_adjacent_generation_and_missing_parent_digest():
    with pytest.raises(EvolutionaryReadinessError, match="generation"):
        Stage176ArtifactManifestBuilder().build(replace(candidate(), proposed_generation=7))
    with pytest.raises(EvolutionaryReadinessError, match="digest"):
        Stage176ArtifactManifestBuilder().build(
            replace(candidate(), parent_artifact_digests=("bad", digest("parent-b")))
        )


def test_stage176_hold_and_kill_switch_fail_closed():
    with pytest.raises(EvolutionaryReadinessError):
        Stage176ArtifactManifestBuilder().build(candidate(), hold_active=True)
    with pytest.raises(EvolutionaryReadinessError):
        Stage176ArtifactManifestBuilder().build(candidate(), kill_switch_active=True)


def test_stage177_requires_distinct_signed_reruns_and_identical_result_digest():
    report = reproducibility()
    assert report.reproducible and len(report.run_ids) == 2
    assert len(set(report.runner_ids)) == 2
    assert len(set(report.evaluator_ids)) == 2
    assert report.proposal_only and not report.execution_authorized
    assert not report.model_merge_authorized and not report.weight_mutation_authorized
    divergent = reproducibility(result_values=[digest("result-a"), digest("result-b")])
    assert not divergent.reproducible


def test_stage177_rejects_replay_lineage_and_bad_signature():
    m = manifest()
    run = ReproducibilityRun(
        m.manifest_digest, m.candidate_artifact_digest, m.evaluation_suite_digest,
        "runner-a", "evaluator-a", "run-a", digest("result"), True, "signature",
    )
    with pytest.raises(EvolutionaryReadinessError, match="unique"):
        Stage177ReproducibilityVerifier().build(
            m, (run, replace(run, run_id="run-b")),
            verify_signature=lambda _: True,
        )
    with pytest.raises(EvolutionaryReadinessError, match="signature"):
        Stage177ReproducibilityVerifier().build(
            m, (run, replace(run, run_id="run-b", runner_id="runner-b",
                              evaluator_id="evaluator-b")),
            verify_signature=lambda _: False,
        )
    with pytest.raises(EvolutionaryReadinessError, match="HOLD"):
        Stage177ReproducibilityVerifier().build(
            m, (run, replace(run, run_id="run-b", runner_id="runner-b",
                              evaluator_id="evaluator-b")),
            verify_signature=lambda _: True, hold_active=True,
        )


def test_stage178_local_resource_feasibility_and_fail_closed_overages():
    m = manifest()
    rep = reproducibility(m)
    feasible = resource_report(m, rep)
    assert feasible.feasible and feasible.proposal_only
    assert not feasible.execution_authorized
    over = resource_report(
        m, rep, ResourceEstimate(8192, 2048, 120, 2.0, digest("estimate"))
    )
    assert not over.feasible
    assert "RAM estimate exceeds local envelope" in over.reasons


def test_stage178_rejects_cloud_or_paid_fallback_and_hold():
    m = manifest()
    rep = reproducibility(m)
    with pytest.raises(EvolutionaryReadinessError, match="local-only"):
        resource_report(m, rep, envelope=ResourceEnvelope(
            4096, 8192, 600, 4.0, local_only=False
        ))
    with pytest.raises(EvolutionaryReadinessError, match="HOLD"):
        Stage178ResourceFeasibilityGate().assess(
            m, rep, ResourceEstimate(1024, 2048, 120, 2.0, digest("estimate")),
            ResourceEnvelope(4096, 8192, 600, 4.0), hold_active=True,
        )


def test_stage179_requires_independent_holdout_and_detects_failures():
    m = manifest()
    passed = holdout_report(m)
    assert passed.passed and passed.proposal_only
    assert len(passed.evaluator_ids) == 2
    assert not passed.selection_authorized
    failed = holdout_report(m, safety=False, contamination=False, robustness=.5)
    assert not failed.passed
    assert "holdout safety failure" in failed.reasons
    assert "holdout contamination check failed" in failed.reasons
    assert "holdout robustness below threshold" in failed.reasons


def test_stage179_rejects_replay_and_signature_failure():
    m = manifest()
    item = HoldoutEvidence(
        m.manifest_digest, m.candidate_artifact_digest, digest("holdout-suite"),
        "holdout-a", "evaluator-a", True, .99, True, "sig", digest("evidence-a"),
    )
    with pytest.raises(EvolutionaryReadinessError, match="replay"):
        Stage179HoldoutRobustnessGate().build(
            m, (item, replace(item, trial_id="holdout-b")),
            verify_signature=lambda _: True,
        )
    with pytest.raises(EvolutionaryReadinessError, match="signature"):
        Stage179HoldoutRobustnessGate().build(
            m, (item, replace(item, trial_id="holdout-b", evaluator_id="evaluator-b",
                               evidence_digest=digest("evidence-b"))),
            verify_signature=lambda _: False,
        )


def test_stage180_builds_exact_candidate_human_approval_packet_only():
    m = manifest()
    rep = reproducibility(m)
    resources = resource_report(m, rep)
    holdout = holdout_report(m)
    certificate = Stage180HumanApprovalPackager().build(
        m, rep, resources, holdout, rollback_artifact_digest=digest("rollback")
    )
    assert certificate.candidate_id == m.candidate_id
    assert certificate.exact_candidate_bound and certificate.approval_required
    assert not certificate.human_approval_granted
    assert certificate.proposal_only
    assert not certificate.model_merge_authorized
    assert not certificate.weight_mutation_authorized
    assert not certificate.generation_advanced
    assert not certificate.model_activated
    assert not certificate.production_switch_authorized


def test_stage180_rejects_missing_gate_and_lineage_drift():
    m = manifest()
    rep = reproducibility(m)
    resources = resource_report(m, rep)
    holdout = holdout_report(m, safety=False)
    with pytest.raises(EvolutionaryReadinessError, match="all reproducibility"):
        Stage180HumanApprovalPackager().build(
            m, rep, resources, holdout, rollback_artifact_digest=digest("rollback")
        )
    with pytest.raises(EvolutionaryReadinessError, match="lineage"):
        Stage180HumanApprovalPackager().build(
            m, rep, replace(resources, manifest_digest=digest("other")),
            holdout, rollback_artifact_digest=digest("rollback")
        )


@pytest.mark.parametrize("stage", [176, 177, 178, 179, 180])
def test_each_stage_preserves_proposal_only_and_human_authority(stage):
    m = manifest()
    rep = reproducibility(m)
    resources = resource_report(m, rep)
    holdout = holdout_report(m)
    if stage == 176:
        assert not m.model_merge_authorized and not m.weight_mutation_authorized
    elif stage == 177:
        assert not rep.execution_authorized and not rep.model_merge_authorized
    elif stage == 178:
        assert not resources.execution_authorized and not resources.paid_api_authorized
    elif stage == 179:
        assert not holdout.selection_authorized and not holdout.model_merge_authorized
    else:
        cert = Stage180HumanApprovalPackager().build(
            m, rep, resources, holdout, rollback_artifact_digest=digest("rollback")
        )
        assert cert.approval_required and not cert.human_approval_granted
