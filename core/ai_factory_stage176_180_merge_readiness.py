"""Stages 176-180: immutable provenance, reproducibility, feasibility and approval readiness.

All outputs are evidence packages and proposals. This module does not execute
models, merge tensors, mutate weights, advance generations, activate models,
or change production routing.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class EvolutionaryReadinessError(ValueError):
    """Raised when lineage, evidence, resource, or safety checks fail."""


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()


def _require_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise EvolutionaryReadinessError(f"{label} must be a lowercase SHA-256 digest")


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EvolutionaryReadinessError(f"{label} identity invalid")


@dataclass(frozen=True)
class SelectedMergeCandidate:
    candidate_id: str
    strategy: str
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    selection_digest: str
    source_generation: int
    proposed_generation: int
    license_id: str


@dataclass(frozen=True)
class ImmutableArtifactManifest:
    candidate_id: str
    candidate_artifact_digest: str
    parent_model_ids: tuple[str, ...]
    parent_artifact_digests: tuple[str, ...]
    evaluation_suite_digest: str
    selection_digest: str
    source_generation: int
    proposed_generation: int
    strategy: str
    license_id: str
    manifest_digest: str
    immutable: bool = True
    proposal_only: bool = True
    artifact_write_authorized: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False


class Stage176ArtifactManifestBuilder:
    """Packages exact parent, candidate and evaluation lineage without writing artifacts."""

    def build(
        self,
        candidate: SelectedMergeCandidate,
        *,
        hold_active: bool = False,
        kill_switch_active: bool = False,
    ) -> ImmutableArtifactManifest:
        if hold_active or kill_switch_active:
            raise EvolutionaryReadinessError("HOLD or kill switch blocks Stage 176")
        if not isinstance(candidate, SelectedMergeCandidate):
            raise EvolutionaryReadinessError("typed selected candidate required")
        _require_id(candidate.candidate_id, "candidate")
        _require_digest(candidate.candidate_artifact_digest, "candidate artifact")
        _require_digest(candidate.evaluation_suite_digest, "evaluation suite")
        _require_digest(candidate.selection_digest, "selection")
        if (not candidate.strategy or not candidate.license_id
                or len(candidate.parent_model_ids) != 2
                or len(candidate.parent_artifact_digests) != 2
                or candidate.parent_model_ids[0] == candidate.parent_model_ids[1]):
            raise EvolutionaryReadinessError("two distinct, licensed parent artifacts are required")
        for item in candidate.parent_model_ids:
            _require_id(item, "parent model")
        for item in candidate.parent_artifact_digests:
            _require_digest(item, "parent artifact")
        if (not isinstance(candidate.source_generation, int)
                or isinstance(candidate.source_generation, bool)
                or candidate.source_generation < 0
                or candidate.proposed_generation != candidate.source_generation + 1):
            raise EvolutionaryReadinessError("candidate generation lineage is not adjacent")
        payload = {
            "candidate_id": candidate.candidate_id,
            "candidate_artifact_digest": candidate.candidate_artifact_digest,
            "parent_model_ids": list(candidate.parent_model_ids),
            "parent_artifact_digests": list(candidate.parent_artifact_digests),
            "evaluation_suite_digest": candidate.evaluation_suite_digest,
            "selection_digest": candidate.selection_digest,
            "source_generation": candidate.source_generation,
            "proposed_generation": candidate.proposed_generation,
            "strategy": candidate.strategy,
            "license_id": candidate.license_id,
        }
        return ImmutableArtifactManifest(
            candidate.candidate_id, candidate.candidate_artifact_digest,
            candidate.parent_model_ids, candidate.parent_artifact_digests,
            candidate.evaluation_suite_digest, candidate.selection_digest,
            candidate.source_generation, candidate.proposed_generation,
            candidate.strategy, candidate.license_id, _hash(payload),
        )


@dataclass(frozen=True)
class ReproducibilityRun:
    manifest_digest: str
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    runner_id: str
    evaluator_id: str
    run_id: str
    result_digest: str
    passed: bool
    signature: str


@dataclass(frozen=True)
class ReproducibilityReport:
    manifest_digest: str
    run_ids: tuple[str, ...]
    runner_ids: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    result_digests: tuple[str, ...]
    reproducible: bool
    report_digest: str
    proposal_only: bool = True
    execution_authorized: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False


class Stage177ReproducibilityVerifier:
    """Verifies supplied independent rerun attestations; it never launches a rerun."""

    def build(
        self,
        manifest: ImmutableArtifactManifest,
        runs: Sequence[ReproducibilityRun],
        *,
        verify_signature: Callable[[ReproducibilityRun], bool],
        hold_active: bool = False,
        minimum_runs: int = 2,
    ) -> ReproducibilityReport:
        if hold_active:
            raise EvolutionaryReadinessError("HOLD blocks Stage 177")
        if (not isinstance(manifest, ImmutableArtifactManifest)
                or not manifest.immutable or not manifest.proposal_only
                or manifest.artifact_write_authorized or manifest.model_merge_authorized
                or manifest.weight_mutation_authorized or manifest.generation_advanced):
            raise EvolutionaryReadinessError("unsafe or mutable Stage 176 manifest")
        _require_digest(manifest.manifest_digest, "manifest")
        if not callable(verify_signature) or not isinstance(minimum_runs, int) or isinstance(minimum_runs, bool) or not 2 <= minimum_runs <= 8:
            raise EvolutionaryReadinessError("independent signature verifier and bounded repeats required")
        if not isinstance(runs, Sequence) or not minimum_runs <= len(runs) <= 8:
            raise EvolutionaryReadinessError("reproducibility run count outside bounds")
        ids, runners, evaluators, results = set(), set(), set(), set()
        passed = True
        for run in runs:
            if not isinstance(run, ReproducibilityRun):
                raise EvolutionaryReadinessError("typed reproducibility run required")
            for value, label in (
                (run.manifest_digest, "run manifest"),
                (run.candidate_artifact_digest, "run artifact"),
                (run.evaluation_suite_digest, "run suite"),
                (run.result_digest, "run result"),
            ):
                _require_digest(value, label)
            for value, label in ((run.run_id, "run"), (run.runner_id, "runner"), (run.evaluator_id, "evaluator")):
                _require_id(value, label)
            if (run.manifest_digest != manifest.manifest_digest
                    or run.candidate_artifact_digest != manifest.candidate_artifact_digest
                    or run.evaluation_suite_digest != manifest.evaluation_suite_digest):
                raise EvolutionaryReadinessError("rerun manifest, artifact, or suite lineage drift")
            if run.run_id in ids or run.runner_id in runners or run.evaluator_id in evaluators:
                raise EvolutionaryReadinessError("reruns require unique run, runner and evaluator identities")
            if not run.signature or len(run.signature) > 8192 or not verify_signature(run):
                raise EvolutionaryReadinessError("rerun signature verification failed")
            ids.add(run.run_id); runners.add(run.runner_id); evaluators.add(run.evaluator_id)
            results.add(run.result_digest)
            passed = passed and run.passed
        reproducible = passed and len(results) == 1
        payload = {
            "manifest": manifest.manifest_digest,
            "runs": sorted(ids), "runners": sorted(runners),
            "evaluators": sorted(evaluators), "results": sorted(results),
            "reproducible": reproducible,
        }
        return ReproducibilityReport(
            manifest.manifest_digest, tuple(sorted(ids)), tuple(sorted(runners)),
            tuple(sorted(evaluators)), tuple(sorted(results)), reproducible, _hash(payload),
        )


@dataclass(frozen=True)
class ResourceEnvelope:
    max_ram_mb: int
    max_disk_mb: int
    max_runtime_seconds: int
    max_cpu_cores: float
    local_only: bool = True
    paid_api_allowed: bool = False
    cloud_fallback_allowed: bool = False


@dataclass(frozen=True)
class ResourceEstimate:
    ram_mb: int
    disk_mb: int
    runtime_seconds: int
    cpu_cores: float
    source_digest: str


@dataclass(frozen=True)
class ResourceFeasibilityReport:
    feasible: bool
    reasons: tuple[str, ...]
    manifest_digest: str
    estimate_digest: str
    envelope_digest: str
    report_digest: str
    proposal_only: bool = True
    execution_authorized: bool = False
    cloud_fallback_authorized: bool = False
    paid_api_authorized: bool = False


class Stage178ResourceFeasibilityGate:
    """Checks declared local resource bounds; it does not reserve or consume resources."""

    def assess(
        self,
        manifest: ImmutableArtifactManifest,
        reproducibility: ReproducibilityReport,
        estimate: ResourceEstimate,
        envelope: ResourceEnvelope,
        *,
        hold_active: bool = False,
        budget_available: bool = True,
    ) -> ResourceFeasibilityReport:
        if hold_active or not budget_available:
            raise EvolutionaryReadinessError("HOLD or unavailable budget blocks Stage 178")
        if (not manifest.proposal_only or not reproducibility.proposal_only
                or manifest.model_merge_authorized or manifest.weight_mutation_authorized
                or reproducibility.execution_authorized or reproducibility.model_merge_authorized):
            raise EvolutionaryReadinessError("upstream authority flags are unsafe")
        if reproducibility.manifest_digest != manifest.manifest_digest or not reproducibility.reproducible:
            raise EvolutionaryReadinessError("reproducibility evidence is missing or mismatched")
        _require_digest(estimate.source_digest, "resource estimate source")
        if not isinstance(envelope, ResourceEnvelope) or not envelope.local_only or envelope.paid_api_allowed or envelope.cloud_fallback_allowed:
            raise EvolutionaryReadinessError("resource envelope must be local-only with no paid or cloud fallback")
        limits = (envelope.max_ram_mb, envelope.max_disk_mb, envelope.max_runtime_seconds)
        values = (estimate.ram_mb, estimate.disk_mb, estimate.runtime_seconds)
        if (any(not isinstance(x, int) or isinstance(x, bool) or x <= 0 for x in limits + values)
                or not isinstance(envelope.max_cpu_cores, (int, float))
                or not math.isfinite(envelope.max_cpu_cores) or envelope.max_cpu_cores <= 0
                or not isinstance(estimate.cpu_cores, (int, float))
                or not math.isfinite(estimate.cpu_cores) or estimate.cpu_cores <= 0):
            raise EvolutionaryReadinessError("resource estimates and limits must be positive finite values")
        reasons = []
        for value, limit, label in zip(values, limits, ("RAM", "disk", "runtime")):
            if value > limit:
                reasons.append(f"{label} estimate exceeds local envelope")
        if estimate.cpu_cores > envelope.max_cpu_cores:
            reasons.append("CPU estimate exceeds local envelope")
        envelope_digest = _hash({
            "ram": envelope.max_ram_mb, "disk": envelope.max_disk_mb,
            "runtime": envelope.max_runtime_seconds, "cpu": envelope.max_cpu_cores,
            "local_only": envelope.local_only, "paid_api": envelope.paid_api_allowed,
            "cloud_fallback": envelope.cloud_fallback_allowed,
        })
        estimate_digest = _hash({
            "ram": estimate.ram_mb, "disk": estimate.disk_mb,
            "runtime": estimate.runtime_seconds, "cpu": estimate.cpu_cores,
            "source": estimate.source_digest,
        })
        feasible = not reasons
        report_digest = _hash({
            "manifest": manifest.manifest_digest, "reproducibility": reproducibility.report_digest,
            "estimate": estimate_digest, "envelope": envelope_digest,
            "feasible": feasible, "reasons": reasons,
        })
        return ResourceFeasibilityReport(
            feasible, tuple(reasons), manifest.manifest_digest,
            estimate_digest, envelope_digest, report_digest,
        )


@dataclass(frozen=True)
class HoldoutEvidence:
    manifest_digest: str
    candidate_artifact_digest: str
    holdout_suite_digest: str
    trial_id: str
    evaluator_id: str
    safety_passed: bool
    robustness_score: float
    contamination_check_passed: bool
    signature: str
    evidence_digest: str


@dataclass(frozen=True)
class HoldoutReport:
    manifest_digest: str
    holdout_suite_digest: str
    evidence_digests: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    passed: bool
    reasons: tuple[str, ...]
    report_digest: str
    proposal_only: bool = True
    selection_authorized: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False


class Stage179HoldoutRobustnessGate:
    """Requires signed, distinct holdout evidence and rejects contaminated or weak results."""

    def build(
        self,
        manifest: ImmutableArtifactManifest,
        evidence: Sequence[HoldoutEvidence],
        *,
        verify_signature: Callable[[HoldoutEvidence], bool],
        hold_active: bool = False,
        minimum_trials: int = 2,
        minimum_robustness: float = 0.90,
    ) -> HoldoutReport:
        if hold_active:
            raise EvolutionaryReadinessError("HOLD blocks Stage 179")
        if (not manifest.proposal_only or manifest.model_merge_authorized
                or manifest.weight_mutation_authorized or manifest.generation_advanced):
            raise EvolutionaryReadinessError("unsafe Stage 176 manifest")
        if not callable(verify_signature) or not isinstance(minimum_trials, int) or isinstance(minimum_trials, bool) or not 2 <= minimum_trials <= 16:
            raise EvolutionaryReadinessError("independent verifier and bounded holdout repeats required")
        if not isinstance(minimum_robustness, (int, float)) or isinstance(minimum_robustness, bool) or not math.isfinite(minimum_robustness) or not 0.5 <= minimum_robustness <= 1:
            raise EvolutionaryReadinessError("robustness threshold outside bounds")
        if not isinstance(evidence, Sequence) or not minimum_trials <= len(evidence) <= 16:
            raise EvolutionaryReadinessError("holdout evidence count outside bounds")
        trials, evaluators, digests = set(), set(), set()
        reasons = []
        for item in evidence:
            if not isinstance(item, HoldoutEvidence):
                raise EvolutionaryReadinessError("typed holdout evidence required")
            for value, label in (
                (item.manifest_digest, "holdout manifest"),
                (item.candidate_artifact_digest, "holdout artifact"),
                (item.holdout_suite_digest, "holdout suite"),
                (item.evidence_digest, "holdout evidence"),
            ):
                _require_digest(value, label)
            for value, label in ((item.trial_id, "holdout trial"), (item.evaluator_id, "holdout evaluator")):
                _require_id(value, label)
            if item.manifest_digest != manifest.manifest_digest or item.candidate_artifact_digest != manifest.candidate_artifact_digest:
                raise EvolutionaryReadinessError("holdout candidate lineage mismatch")
            if item.trial_id in trials or item.evaluator_id in evaluators or item.evidence_digest in digests:
                raise EvolutionaryReadinessError("holdout evidence replay or evaluator reuse")
            if not item.signature or len(item.signature) > 8192 or not verify_signature(item):
                raise EvolutionaryReadinessError("holdout signature verification failed")
            if not math.isfinite(item.robustness_score) or not 0 <= item.robustness_score <= 1:
                raise EvolutionaryReadinessError("holdout robustness score invalid")
            trials.add(item.trial_id); evaluators.add(item.evaluator_id); digests.add(item.evidence_digest)
            if not item.safety_passed:
                reasons.append("holdout safety failure")
            if not item.contamination_check_passed:
                reasons.append("holdout contamination check failed")
            if item.robustness_score < minimum_robustness:
                reasons.append("holdout robustness below threshold")
        passed = not reasons
        payload = {
            "manifest": manifest.manifest_digest, "suite": evidence[0].holdout_suite_digest,
            "evidence": sorted(digests), "evaluators": sorted(evaluators),
            "passed": passed, "reasons": sorted(set(reasons)),
        }
        return HoldoutReport(
            manifest.manifest_digest, evidence[0].holdout_suite_digest,
            tuple(sorted(digests)), tuple(sorted(evaluators)), passed,
            tuple(sorted(set(reasons))), _hash(payload),
        )


@dataclass(frozen=True)
class HumanApprovalCertificate:
    candidate_id: str
    manifest_digest: str
    reproducibility_report_digest: str
    resource_report_digest: str
    holdout_report_digest: str
    approval_packet_digest: str
    approval_required: bool
    exact_candidate_bound: bool
    rollback_artifact_digest: str
    digest: str
    proposal_only: bool = True
    human_approval_granted: bool = False
    model_merge_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advanced: bool = False
    model_activated: bool = False
    production_switch_authorized: bool = False


class Stage180HumanApprovalPackager:
    """Creates a review certificate; a separate human decision is still mandatory."""

    def build(
        self,
        manifest: ImmutableArtifactManifest,
        reproducibility: ReproducibilityReport,
        resources: ResourceFeasibilityReport,
        holdout: HoldoutReport,
        *,
        rollback_artifact_digest: str,
        hold_active: bool = False,
        kill_switch_active: bool = False,
    ) -> HumanApprovalCertificate:
        if hold_active or kill_switch_active:
            raise EvolutionaryReadinessError("HOLD or kill switch blocks Stage 180")
        if (not manifest.proposal_only or manifest.model_merge_authorized
                or manifest.weight_mutation_authorized or manifest.generation_advanced
                or not reproducibility.proposal_only or reproducibility.execution_authorized
                or not resources.proposal_only or resources.execution_authorized
                or resources.cloud_fallback_authorized or resources.paid_api_authorized
                or not holdout.proposal_only or holdout.selection_authorized
                or holdout.model_merge_authorized or holdout.weight_mutation_authorized):
            raise EvolutionaryReadinessError("upstream proposal or authority state is unsafe")
        if (reproducibility.manifest_digest != manifest.manifest_digest
                or resources.manifest_digest != manifest.manifest_digest
                or holdout.manifest_digest != manifest.manifest_digest):
            raise EvolutionaryReadinessError("Stage 176-179 manifest lineage mismatch")
        if not reproducibility.reproducible or not resources.feasible or not holdout.passed:
            raise EvolutionaryReadinessError("all reproducibility, resource and holdout gates must pass")
        for value, label in (
            (reproducibility.report_digest, "reproducibility report"),
            (resources.report_digest, "resource report"),
            (holdout.report_digest, "holdout report"),
            (rollback_artifact_digest, "rollback artifact"),
        ):
            _require_digest(value, label)
        packet = _hash({
            "candidate": manifest.candidate_id,
            "manifest": manifest.manifest_digest,
            "reproducibility": reproducibility.report_digest,
            "resources": resources.report_digest,
            "holdout": holdout.report_digest,
            "rollback": rollback_artifact_digest,
            "license": manifest.license_id,
        })
        digest = _hash({
            "candidate": manifest.candidate_id, "packet": packet,
            "approval_required": True, "exact_candidate_bound": True,
        })
        return HumanApprovalCertificate(
            manifest.candidate_id, manifest.manifest_digest,
            reproducibility.report_digest, resources.report_digest,
            holdout.report_digest, packet, True, True,
            rollback_artifact_digest, digest,
        )


__all__ = [
    "EvolutionaryReadinessError", "SelectedMergeCandidate",
    "ImmutableArtifactManifest", "Stage176ArtifactManifestBuilder",
    "ReproducibilityRun", "ReproducibilityReport",
    "Stage177ReproducibilityVerifier", "ResourceEnvelope", "ResourceEstimate",
    "ResourceFeasibilityReport", "Stage178ResourceFeasibilityGate",
    "HoldoutEvidence", "HoldoutReport", "Stage179HoldoutRobustnessGate",
    "HumanApprovalCertificate", "Stage180HumanApprovalPackager",
]
