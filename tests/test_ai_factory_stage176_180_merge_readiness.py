from dataclasses import replace
import pytest
from core.ai_factory_stage176_180_merge_readiness import (
    HoldoutEvidence, LocalResourceEnvelope, LocalResourceEstimate, MergeReadinessError,
    ReproductionRun, Stage176ArtifactManifestBuilder, Stage177ReproducibilityVerifier,
    Stage178LocalResourceGate, Stage179HoldoutRobustnessGate, Stage180HumanApprovalPackager,
)
H="a"*64
def manifest(candidate_id="candidate-7"):
    return Stage176ArtifactManifestBuilder().build(candidate_id=candidate_id,candidate_artifact_digest="1"*64,
        parent_model_ids=("parent-a","parent-b"),parent_artifact_digests=("2"*64,"3"*64),
        compatibility_digest="4"*64,evaluation_report_digest="5"*64,selection_digest="6"*64,
        evaluation_suite_digest="7"*64,source_generation=10,proposed_generation=11,
        license_ids=("Apache-2.0",),provenance_digest="8"*64,rollback_artifact_digest="9"*64)
def runs(m):
    return tuple(ReproductionRun(m.digest,m.candidate_artifact_digest,m.evaluation_suite_digest,
        f"run-{i}",f"evaluator-{i}",f"executor-{i}","b"*64,"c"*64,"sig") for i in (1,2))
def resource_report():
    return Stage178LocalResourceGate().build(LocalResourceEstimate(2,4096,0,10000,600,10),
        LocalResourceEnvelope(4,8192,0,20000,1200,20))
def holdouts(m):
    return tuple(HoldoutEvidence(m.digest,m.candidate_artifact_digest,m.evaluation_suite_digest,
        "d"*64,"e"*64,f"trial-{i}",f"holdout-evaluator-{i}",True,.99,True,"sig") for i in (1,2))
def test_stages_176_to_180_create_human_review_package_without_authority():
    m=manifest(); r=Stage177ReproducibilityVerifier().build(m,runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    h=Stage179HoldoutRobustnessGate().build(m,holdouts(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    c=Stage180HumanApprovalPackager().build(m,r,resource_report(),h,verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest,verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)
    assert c.ready_for_human_review and c.proposal_only and c.human_approval_required
    assert not c.merge_execution_authorized and not c.weight_mutation_authorized
    assert not c.generation_advance_authorized and not c.model_activation_authorized and not c.production_switch_authorized
def test_stage176_rejects_generation_gap_and_missing_license():
    with pytest.raises(MergeReadinessError,match="generation"):
        Stage176ArtifactManifestBuilder().build(candidate_id="x",candidate_artifact_digest=H,
            parent_model_ids=("a","b"),parent_artifact_digests=(H,H),compatibility_digest=H,
            evaluation_report_digest=H,selection_digest=H,evaluation_suite_digest=H,
            source_generation=1,proposed_generation=3,license_ids=("MIT",),provenance_digest=H,rollback_artifact_digest=H)
    with pytest.raises(MergeReadinessError,match="license"):
        Stage176ArtifactManifestBuilder().build(candidate_id="x",candidate_artifact_digest=H,
            parent_model_ids=("a","b"),parent_artifact_digests=(H,H),compatibility_digest=H,
            evaluation_report_digest=H,selection_digest=H,evaluation_suite_digest=H,
            source_generation=1,proposed_generation=2,license_ids=(),provenance_digest=H,rollback_artifact_digest=H)
def test_stage177_rejects_replay_signature_drift_and_non_reproducibility():
    m=manifest(); rs=runs(m)
    with pytest.raises(MergeReadinessError,match="replayed"):
        Stage177ReproducibilityVerifier().build(m,(rs[0],rs[0]),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    with pytest.raises(MergeReadinessError,match="signature"):
        Stage177ReproducibilityVerifier().build(m,rs,verify_signature=lambda x:False,sign_report=lambda d:'signed:'+d)
    with pytest.raises(MergeReadinessError,match="deterministic"):
        Stage177ReproducibilityVerifier().build(m,(rs[0],replace(rs[1],result_digest="f"*64)),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
def test_stage177_requires_distinct_evaluators_and_executors():
    m=manifest(); rs=runs(m)
    with pytest.raises(MergeReadinessError,match="distinct evaluator"):
        Stage177ReproducibilityVerifier().build(m,(rs[0],replace(rs[1],evaluator_id=rs[0].evaluator_id)),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    with pytest.raises(MergeReadinessError,match="distinct executor"):
        Stage177ReproducibilityVerifier().build(m,(rs[0],replace(rs[1],executor_id=rs[0].executor_id)),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
def test_stage178_fails_closed_on_over_budget_and_cloud_fallback():
    report=Stage178LocalResourceGate().build(LocalResourceEstimate(8,9000,0,30000,1800,40),
        LocalResourceEnvelope(4,8192,0,20000,1200,20))
    assert not report.feasible and len(report.reasons)==5
    with pytest.raises(MergeReadinessError,match="fallback"):
        Stage178LocalResourceGate().build(LocalResourceEstimate(1,1024,0,1000,60,1),
            LocalResourceEnvelope(4,8192,0,20000,1200,20,cloud_fallback_allowed=True))
def test_stage179_rejects_contamination_and_low_coverage():
    m=manifest(); items=holdouts(m)
    with pytest.raises(MergeReadinessError,match="contamination"):
        Stage179HoldoutRobustnessGate().build(m,(replace(items[0],contamination_attested=False),items[1]),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    low=Stage179HoldoutRobustnessGate().build(m,(replace(items[0],coverage=.5),items[1]),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    assert not low.passed
def test_stage180_requires_matching_manifest_and_all_gates():
    m=manifest(); r=Stage177ReproducibilityVerifier().build(m,runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    h=Stage179HoldoutRobustnessGate().build(m,holdouts(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    with pytest.raises(MergeReadinessError,match="lineage"):
        Stage180HumanApprovalPackager().build(manifest("candidate-other"),r,resource_report(),h,verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest,verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)
    blocked=Stage180HumanApprovalPackager().build(m,r,
        Stage178LocalResourceGate().build(LocalResourceEstimate(99,99999,0,99999,99999,999),
        LocalResourceEnvelope(1,1024,0,1024,60,1)),h,verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest,verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)
    assert not blocked.ready_for_human_review and not blocked.merge_execution_authorized
@pytest.mark.parametrize("stage",range(176,181))
def test_hold_blocks_every_stage(stage):
    m=manifest()
    with pytest.raises(MergeReadinessError,match="HOLD"):
        if stage==176:
            Stage176ArtifactManifestBuilder().build(candidate_id="x",candidate_artifact_digest=H,
                parent_model_ids=("a","b"),parent_artifact_digests=(H,H),compatibility_digest=H,
                evaluation_report_digest=H,selection_digest=H,evaluation_suite_digest=H,
                source_generation=1,proposed_generation=2,license_ids=("MIT",),provenance_digest=H,rollback_artifact_digest=H,hold_active=True)
        elif stage==177:
            Stage177ReproducibilityVerifier().build(m,runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d,hold_active=True)
        elif stage==178:
            Stage178LocalResourceGate().build(LocalResourceEstimate(1,1,0,1,1,1),LocalResourceEnvelope(2,2,0,2,2,2),hold_active=True)
        elif stage==179:
            Stage179HoldoutRobustnessGate().build(m,holdouts(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d,hold_active=True)
        else:
            r=Stage177ReproducibilityVerifier().build(m,runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
            h=Stage179HoldoutRobustnessGate().build(m,holdouts(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
            Stage180HumanApprovalPackager().build(m,r,resource_report(),h,verify_reproducibility_signature=lambda x:True,verify_holdout_signature=lambda x:True,hold_active=True)


def test_stage177_and_stage180_reject_forged_manifest_or_report_digest():
    m=manifest()
    with pytest.raises(MergeReadinessError,match="manifest digest"):
        Stage177ReproducibilityVerifier().build(replace(m,digest="f"*64),runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    r=Stage177ReproducibilityVerifier().build(m,runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    h=Stage179HoldoutRobustnessGate().build(m,holdouts(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    with pytest.raises(MergeReadinessError,match="reproducibility report digest"):
        Stage180HumanApprovalPackager().build(m,replace(r,digest="f"*64),resource_report(),h,verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest,verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)
    with pytest.raises(MergeReadinessError,match="holdout report digest"):
        Stage180HumanApprovalPackager().build(m,r,resource_report(),replace(h,digest="f"*64),verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest,verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)
    with pytest.raises(MergeReadinessError,match="resource report digest"):
        Stage180HumanApprovalPackager().build(m,r,replace(resource_report(),digest="f"*64),h,verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest,verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)


def test_stage180_rejects_unsigned_or_forged_stage_reports():
    m=manifest()
    r=Stage177ReproducibilityVerifier().build(m,runs(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    h=Stage179HoldoutRobustnessGate().build(m,holdouts(m),verify_signature=lambda x:True,sign_report=lambda d:'signed:'+d)
    kwargs=dict(verify_reproducibility_signature=lambda x:x.signature=='signed:'+x.digest, verify_holdout_signature=lambda x:x.signature=='signed:'+x.digest)
    with pytest.raises(MergeReadinessError,match='reproducibility report signature'):
        Stage180HumanApprovalPackager().build(m,replace(r,signature='forged'),resource_report(),h,**kwargs)
    with pytest.raises(MergeReadinessError,match='holdout report signature'):
        Stage180HumanApprovalPackager().build(m,r,resource_report(),replace(h,signature='forged'),**kwargs)
