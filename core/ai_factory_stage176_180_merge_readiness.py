"""Stages 176-180: reproducible, local-only merge readiness evidence.

All outputs are immutable proposals. This module never executes a model,
mutates weights, advances a generation, activates a model, or deploys.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, math, re
from typing import Callable, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

class MergeReadinessError(ValueError):
    """Invalid artifact lineage, reproducibility, resource, or approval evidence."""

def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def _check_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise MergeReadinessError(f"{label} must be a lowercase SHA-256 digest")

def _check_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise MergeReadinessError(f"{label} is invalid")

@dataclass(frozen=True)
class MergeArtifactManifest:
    candidate_id: str
    candidate_artifact_digest: str
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    compatibility_digest: str
    evaluation_report_digest: str
    selection_digest: str
    evaluation_suite_digest: str
    source_generation: int
    proposed_generation: int
    license_ids: tuple[str, ...]
    provenance_digest: str
    rollback_artifact_digest: str
    digest: str
    proposal_only: bool = True
    weight_mutation_authorized: bool = False
    generation_advance_authorized: bool = False
    model_activation_authorized: bool = False

class Stage176ArtifactManifestBuilder:
    """Creates an immutable digest-bound manifest for one selected candidate."""
    def build(self, *, candidate_id: str, candidate_artifact_digest: str,
              parent_model_ids: Sequence[str], parent_artifact_digests: Sequence[str],
              compatibility_digest: str, evaluation_report_digest: str,
              selection_digest: str, evaluation_suite_digest: str,
              source_generation: int, proposed_generation: int,
              license_ids: Sequence[str], provenance_digest: str,
              rollback_artifact_digest: str, hold_active: bool = False) -> MergeArtifactManifest:
        if hold_active: raise MergeReadinessError("HOLD blocks Stage 176")
        _check_id(candidate_id, "candidate_id")
        for value, label in ((candidate_artifact_digest,"candidate artifact"),(compatibility_digest,"compatibility"),
                             (evaluation_report_digest,"evaluation report"),(selection_digest,"selection"),
                             (evaluation_suite_digest,"evaluation suite"),(provenance_digest,"provenance"),
                             (rollback_artifact_digest,"rollback artifact")):
            _check_digest(value,label)
        if not isinstance(source_generation,int) or isinstance(source_generation,bool) or source_generation < 0:
            raise MergeReadinessError("source generation is invalid")
        if proposed_generation != source_generation + 1:
            raise MergeReadinessError("proposed generation must be exactly one generation ahead")
        ids, digests = tuple(parent_model_ids), tuple(parent_artifact_digests)
        if not 2 <= len(ids) <= 8 or len(ids) != len(digests) or len(set(ids)) != len(ids):
            raise MergeReadinessError("two to eight unique parent identities and matching digests are required")
        for value in ids: _check_id(value,"parent model id")
        for value in digests: _check_digest(value,"parent artifact")
        raw_licenses=tuple(license_ids)
        if not raw_licenses or any(not isinstance(x,str) or not x.strip() for x in raw_licenses):
            raise MergeReadinessError("explicit non-empty license identifiers are required")
        licenses=tuple(sorted(set(raw_licenses)))
        payload={"candidate":candidate_id,"artifact":candidate_artifact_digest,"parents":list(zip(ids,digests)),
                 "compatibility":compatibility_digest,"evaluation":evaluation_report_digest,"selection":selection_digest,
                 "suite":evaluation_suite_digest,"source_generation":source_generation,"proposed_generation":proposed_generation,
                 "licenses":licenses,"provenance":provenance_digest,"rollback":rollback_artifact_digest}
        return MergeArtifactManifest(candidate_id,candidate_artifact_digest,ids,digests,compatibility_digest,
            evaluation_report_digest,selection_digest,evaluation_suite_digest,source_generation,proposed_generation,
            licenses,provenance_digest,rollback_artifact_digest,_digest(payload))

@dataclass(frozen=True)
class ReproductionRun:
    manifest_digest: str
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    run_id: str
    evaluator_id: str
    executor_id: str
    result_digest: str
    metrics_digest: str
    signature: str

@dataclass(frozen=True)
class ReproducibilityReport:
    manifest_digest: str
    run_ids: tuple[str,...]
    evaluator_ids: tuple[str,...]
    executor_ids: tuple[str,...]
    result_digest: str
    metrics_digest: str
    digest: str
    proposal_only: bool = True

class Stage177ReproducibilityVerifier:
    """Verifies repeated independent attestations; does not rerun models."""
    def build(self,manifest:MergeArtifactManifest,runs:Sequence[ReproductionRun],*,
              verify_signature:Callable[[ReproductionRun],bool],hold_active:bool=False,
              minimum_runs:int=2,maximum_runs:int=8)->ReproducibilityReport:
        if hold_active: raise MergeReadinessError("HOLD blocks Stage 177")
        if not manifest.proposal_only or manifest.weight_mutation_authorized or manifest.generation_advance_authorized:
            raise MergeReadinessError("unsafe Stage 176 manifest")
        _check_digest(manifest.digest,"manifest")
        if (not isinstance(minimum_runs,int) or isinstance(minimum_runs,bool)
                or not isinstance(maximum_runs,int) or isinstance(maximum_runs,bool)
                or not 2 <= minimum_runs <= maximum_runs <= 8):
            raise MergeReadinessError("reproduction bounds are invalid")
        if not minimum_runs <= len(runs) <= maximum_runs: raise MergeReadinessError("reproduction run count is outside bounds")
        if any(not isinstance(x,ReproductionRun) for x in runs):
            raise MergeReadinessError("typed reproduction attestations are required")
        if len({x.run_id for x in runs}) != len(runs): raise MergeReadinessError("replayed reproduction run")
        for run in runs:
            for value,label in ((run.manifest_digest,"run manifest"),(run.candidate_artifact_digest,"run artifact"),
                (run.evaluation_suite_digest,"run suite"),(run.result_digest,"run result"),(run.metrics_digest,"run metrics")):
                _check_digest(value,label)
            for value,label in ((run.run_id,"run id"),(run.evaluator_id,"evaluator id"),(run.executor_id,"executor id")):
                _check_id(value,label)
            if not run.signature or not verify_signature(run): raise MergeReadinessError("reproduction signature verification failed")
            if (run.manifest_digest != manifest.digest or run.candidate_artifact_digest != manifest.candidate_artifact_digest
                or run.evaluation_suite_digest != manifest.evaluation_suite_digest):
                raise MergeReadinessError("reproduction lineage or suite drift")
        if len({x.evaluator_id for x in runs}) != len(runs): raise MergeReadinessError("reproduction requires distinct evaluator identities")
        if len({x.executor_id for x in runs}) != len(runs): raise MergeReadinessError("reproduction requires distinct executor identities")
        if len({x.result_digest for x in runs}) != 1 or len({x.metrics_digest for x in runs}) != 1:
            raise MergeReadinessError("reproduction outputs are not deterministic")
        payload={"manifest":manifest.digest,"runs":sorted(x.run_id for x in runs),
                 "evaluators":sorted(x.evaluator_id for x in runs),"executors":sorted(x.executor_id for x in runs),
                 "result":runs[0].result_digest,"metrics":runs[0].metrics_digest}
        return ReproducibilityReport(manifest.digest,tuple(sorted(x.run_id for x in runs)),
            tuple(sorted(x.evaluator_id for x in runs)),tuple(sorted(x.executor_id for x in runs)),
            runs[0].result_digest,runs[0].metrics_digest,_digest(payload))

@dataclass(frozen=True)
class LocalResourceEstimate:
    cpu_cores: float
    ram_mb: int
    vram_mb: int
    disk_mb: int
    runtime_seconds: int
    energy_wh: float

@dataclass(frozen=True)
class LocalResourceEnvelope:
    cpu_cores: float
    ram_mb: int
    vram_mb: int
    disk_mb: int
    runtime_seconds: int
    energy_wh: float
    paid_api_allowed: bool = False
    cloud_fallback_allowed: bool = False

@dataclass(frozen=True)
class ResourceFeasibilityReport:
    feasible: bool
    reasons: tuple[str,...]
    estimate_digest: str
    envelope_digest: str
    digest: str
    local_only: bool = True
    proposal_only: bool = True

class Stage178LocalResourceGate:
    """Checks local resource bounds and forbids paid API/cloud fallback."""
    def build(self,estimate:LocalResourceEstimate,envelope:LocalResourceEnvelope,*,hold_active:bool=False)->ResourceFeasibilityReport:
        if hold_active: raise MergeReadinessError("HOLD blocks Stage 178")
        numeric=(estimate.cpu_cores,estimate.ram_mb,estimate.vram_mb,estimate.disk_mb,estimate.runtime_seconds,estimate.energy_wh,
                 envelope.cpu_cores,envelope.ram_mb,envelope.vram_mb,envelope.disk_mb,envelope.runtime_seconds,envelope.energy_wh)
        if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) or x<0 for x in numeric):
            raise MergeReadinessError("resource estimates and limits must be finite and non-negative")
        if envelope.paid_api_allowed is not False or envelope.cloud_fallback_allowed is not False:
            raise MergeReadinessError("paid API and cloud fallback flags must be explicitly false")
        reasons=[]
        for field in ("cpu_cores","ram_mb","vram_mb","disk_mb","runtime_seconds","energy_wh"):
            if getattr(estimate,field)>getattr(envelope,field): reasons.append(f"{field} exceeds local envelope")
        if envelope.paid_api_allowed: reasons.append("paid API fallback must remain disabled")
        if envelope.cloud_fallback_allowed: reasons.append("cloud fallback must remain disabled")
        ed,ld=_digest(estimate.__dict__),_digest(envelope.__dict__)
        return ResourceFeasibilityReport(not reasons,tuple(reasons),ed,ld,
            _digest({"feasible":not reasons,"reasons":reasons,"estimate":ed,"envelope":ld}))

@dataclass(frozen=True)
class HoldoutEvidence:
    manifest_digest: str
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    holdout_dataset_digest: str
    adversarial_suite_digest: str
    trial_id: str
    evaluator_id: str
    contamination_attested: bool
    coverage: float
    passed: bool
    signature: str

@dataclass(frozen=True)
class HoldoutRobustnessReport:
    manifest_digest: str
    evidence_digests: tuple[str,...]
    evaluator_ids: tuple[str,...]
    holdout_dataset_digest: str
    adversarial_suite_digest: str
    passed: bool
    digest: str
    proposal_only: bool = True

class Stage179HoldoutRobustnessGate:
    """Requires clean, independent holdout/adversarial evidence."""
    def build(self,manifest:MergeArtifactManifest,evidence:Sequence[HoldoutEvidence],*,
              verify_signature:Callable[[HoldoutEvidence],bool],hold_active:bool=False,
              minimum_evaluators:int=2,minimum_coverage:float=0.95)->HoldoutRobustnessReport:
        if hold_active: raise MergeReadinessError("HOLD blocks Stage 179")
        if not 2<=len(evidence)<=8 or not 2<=minimum_evaluators<=8: raise MergeReadinessError("holdout evidence count is outside bounds")
        if any(not isinstance(x,HoldoutEvidence) for x in evidence):
            raise MergeReadinessError("typed holdout attestations are required")
        if not 0.5<=minimum_coverage<=1.0: raise MergeReadinessError("holdout coverage threshold is invalid")
        if len({x.trial_id for x in evidence})!=len(evidence): raise MergeReadinessError("replayed holdout trial")
        for item in evidence:
            for value,label in ((item.manifest_digest,"holdout manifest"),(item.candidate_artifact_digest,"holdout artifact"),
                (item.evaluation_suite_digest,"holdout suite"),(item.holdout_dataset_digest,"holdout dataset"),
                (item.adversarial_suite_digest,"adversarial suite")): _check_digest(value,label)
            _check_id(item.trial_id,"holdout trial id"); _check_id(item.evaluator_id,"holdout evaluator id")
            if not item.signature or not verify_signature(item): raise MergeReadinessError("holdout signature verification failed")
            if (item.manifest_digest!=manifest.digest or item.candidate_artifact_digest!=manifest.candidate_artifact_digest
                or item.evaluation_suite_digest!=manifest.evaluation_suite_digest): raise MergeReadinessError("holdout evidence lineage drift")
            if item.contamination_attested is not True: raise MergeReadinessError("holdout contamination attestation missing")
            if not math.isfinite(item.coverage) or not 0<=item.coverage<=1: raise MergeReadinessError("holdout coverage is invalid")
        evaluators={x.evaluator_id for x in evidence}; datasets={x.holdout_dataset_digest for x in evidence}
        adversarial={x.adversarial_suite_digest for x in evidence}
        if len(datasets)!=1 or len(adversarial)!=1: raise MergeReadinessError("holdout evidence must use one frozen dataset and adversarial suite")
        passed=(len(evaluators)>=minimum_evaluators and all(x.passed is True and x.coverage>=minimum_coverage for x in evidence))
        ds=tuple(sorted(_digest(x.__dict__) for x in evidence))
        payload={"manifest":manifest.digest,"evidence":ds,"evaluators":sorted(evaluators),
                 "dataset":next(iter(datasets)),"adversarial":next(iter(adversarial)),"passed":passed}
        return HoldoutRobustnessReport(manifest.digest,ds,tuple(sorted(evaluators)),next(iter(datasets)),
            next(iter(adversarial)),passed,_digest(payload))

@dataclass(frozen=True)
class MergeReadinessCertificate:
    candidate_id: str
    manifest_digest: str
    reproducibility_digest: str
    resource_report_digest: str
    holdout_report_digest: str
    license_ids: tuple[str,...]
    rollback_artifact_digest: str
    readiness_digest: str
    ready_for_human_review: bool
    proposal_only: bool = True
    human_approval_required: bool = True
    merge_execution_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advance_authorized: bool = False
    model_activation_authorized: bool = False
    production_switch_authorized: bool = False

class Stage180HumanApprovalPackager:
    """Packages evidence for a human decision; cannot issue or simulate approval."""
    def build(self,manifest:MergeArtifactManifest,reproduction:ReproducibilityReport,
              resources:ResourceFeasibilityReport,holdout:HoldoutRobustnessReport,*,
              hold_active:bool=False)->MergeReadinessCertificate:
        if hold_active: raise MergeReadinessError("HOLD blocks Stage 180")
        if not manifest.proposal_only or any((manifest.weight_mutation_authorized,
            manifest.generation_advance_authorized,manifest.model_activation_authorized)):
            raise MergeReadinessError("unsafe manifest authority")
        if not isinstance(reproduction,ReproducibilityReport) or not isinstance(resources,ResourceFeasibilityReport) or not isinstance(holdout,HoldoutRobustnessReport):
            raise MergeReadinessError("typed Stage 177-179 reports are required")
        for value,label in ((reproduction.digest,"reproducibility report"),(resources.digest,"resource report"),(holdout.digest,"holdout report")):
            _check_digest(value,label)
        if reproduction.manifest_digest!=manifest.digest or holdout.manifest_digest!=manifest.digest:
            raise MergeReadinessError("readiness evidence manifest lineage mismatch")
        if not reproduction.proposal_only or not holdout.proposal_only: raise MergeReadinessError("readiness evidence must remain proposal-only")
        if not resources.proposal_only or not resources.local_only: raise MergeReadinessError("resource report is not local-only proposal evidence")
        ready=resources.feasible and holdout.passed
        payload={"candidate":manifest.candidate_id,"manifest":manifest.digest,"reproduction":reproduction.digest,
                 "resources":resources.digest,"holdout":holdout.digest,"licenses":manifest.license_ids,
                 "rollback":manifest.rollback_artifact_digest,"ready":ready}
        return MergeReadinessCertificate(manifest.candidate_id,manifest.digest,reproduction.digest,
            resources.digest,holdout.digest,manifest.license_ids,manifest.rollback_artifact_digest,_digest(payload),ready)

__all__=["MergeReadinessError","MergeArtifactManifest","Stage176ArtifactManifestBuilder",
"ReproductionRun","ReproducibilityReport","Stage177ReproducibilityVerifier","LocalResourceEstimate",
"LocalResourceEnvelope","ResourceFeasibilityReport","Stage178LocalResourceGate","HoldoutEvidence",
"HoldoutRobustnessReport","Stage179HoldoutRobustnessGate","MergeReadinessCertificate","Stage180HumanApprovalPackager"]
