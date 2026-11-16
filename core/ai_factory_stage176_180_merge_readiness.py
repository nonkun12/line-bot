"""Stages 176-180: reproducible, resource-bounded, human-gated merge readiness."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class MergeReadinessError(ValueError):
    """Invalid evidence, resource envelope, holdout result, or approval package."""


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _require_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise MergeReadinessError(f"{label} digest invalid")


@dataclass(frozen=True)
class MergeArtifactManifest:
    candidate_id: str
    candidate_artifact_digest: str
    parent_artifact_digests: tuple[str, ...]
    evaluation_suite_digest: str
    selection_digest: str
    source_generation: int
    proposed_generation: int
    manifest_digest: str
    immutable: bool = True
    proposal_only: bool = True


class Stage176ArtifactManifestBuilder:
    """Binds selected candidate bytes and all upstream evidence into an immutable manifest."""
    def build(self, *, candidate_id: str, candidate_artifact_digest: str,
              parent_artifact_digests: Sequence[str], evaluation_suite_digest: str,
              selection_digest: str, source_generation: int, proposed_generation: int,
              hold_active: bool = False) -> MergeArtifactManifest:
        if hold_active:
            raise MergeReadinessError("HOLD blocks Stage 176")
        if not _ID.fullmatch(candidate_id or ""):
            raise MergeReadinessError("candidate identity invalid")
        for value, label in ((candidate_artifact_digest, "candidate artifact"),
                             (evaluation_suite_digest, "suite"), (selection_digest, "selection")):
            _require_digest(value, label)
        parents = tuple(parent_artifact_digests)
        if not 2 <= len(parents) <= 8:
            raise MergeReadinessError("two to eight parent artifact digests required")
        for value in parents:
            _require_digest(value, "parent artifact")
        if len(set(parents)) != len(parents):
            raise MergeReadinessError("duplicate parent artifact digest")
        if (not isinstance(source_generation, int) or isinstance(source_generation, bool)
                or proposed_generation != source_generation + 1):
            raise MergeReadinessError("generation lineage must be adjacent")
        payload = {"candidate": candidate_id, "artifact": candidate_artifact_digest,
                   "parents": parents, "suite": evaluation_suite_digest,
                   "selection": selection_digest, "source_generation": source_generation,
                   "proposed_generation": proposed_generation}
        return MergeArtifactManifest(candidate_id, candidate_artifact_digest, parents,
                                     evaluation_suite_digest, selection_digest, source_generation,
                                     proposed_generation, _hash(payload))


@dataclass(frozen=True)
class ReproducibilityEvidence:
    manifest_digest: str
    candidate_artifact_digest: str
    evaluation_suite_digest: str
    executor_id: str
    evaluator_id: str
    rerun_id: str
    output_digest: str
    signature: str


@dataclass(frozen=True)
class ReproducibilityReport:
    manifest_digest: str
    rerun_count: int
    executor_ids: tuple[str, ...]
    evaluator_ids: tuple[str, ...]
    output_digests: tuple[str, ...]
    reproducible: bool
    report_digest: str
    proposal_only: bool = True


class Stage177ReproducibilityVerifier:
    """Requires independently signed reruns against identical immutable inputs."""
    def build(self, manifest: MergeArtifactManifest, evidence: Sequence[ReproducibilityEvidence],
              *, verify_signature: Callable[[ReproducibilityEvidence], bool],
              minimum_reruns: int = 2, hold_active: bool = False) -> ReproducibilityReport:
        if hold_active:
            raise MergeReadinessError("HOLD blocks Stage 177")
        if not callable(verify_signature) or not 2 <= minimum_reruns <= 8:
            raise MergeReadinessError("independent verifier and bounded reruns required")
        if not manifest.immutable or not manifest.proposal_only:
            raise MergeReadinessError("manifest must be immutable and proposal-only")
        seen = set()
        rows = []
        for item in evidence:
            if (item.manifest_digest != manifest.manifest_digest
                    or item.candidate_artifact_digest != manifest.candidate_artifact_digest
                    or item.evaluation_suite_digest != manifest.evaluation_suite_digest):
                raise MergeReadinessError("reproducibility input lineage mismatch")
            for value, label in ((item.output_digest, "output"),):
                _require_digest(value, label)
            for value, label in ((item.executor_id, "executor"), (item.evaluator_id, "evaluator"),
                                 (item.rerun_id, "rerun")):
                if not _ID.fullmatch(value or ""):
                    raise MergeReadinessError(f"{label} identity invalid")
            if not item.signature or len(item.signature) > 8192:
                raise MergeReadinessError("signature missing or oversized")
            if item.rerun_id in seen:
                raise MergeReadinessError("replayed rerun")
            if not verify_signature(item):
                raise MergeReadinessError("independent signature verification failed")
            seen.add(item.rerun_id)
            rows.append(item)
        if len(rows) < minimum_reruns:
            raise MergeReadinessError("insufficient reproducibility reruns")
        if len({x.executor_id for x in rows}) != len(rows):
            raise MergeReadinessError("reruns require distinct executors")
        if len({x.evaluator_id for x in rows}) != len(rows):
            raise MergeReadinessError("reruns require distinct evaluators")
        outputs = tuple(sorted(x.output_digest for x in rows))
        reproducible = len(set(outputs)) == 1
        payload = {"manifest": manifest.manifest_digest, "reruns": len(rows),
                   "executors": sorted(x.executor_id for x in rows),
                   "evaluators": sorted(x.evaluator_id for x in rows),
                   "outputs": outputs, "reproducible": reproducible}
        return ReproducibilityReport(manifest.manifest_digest, len(rows),
                                     tuple(sorted(x.executor_id for x in rows)),
                                     tuple(sorted(x.evaluator_id for x in rows)),
                                     outputs, reproducible, _hash(payload))


@dataclass(frozen=True)
class ResourceEnvelope:
    measured_ram_mb: float
    measured_disk_mb: float
    measured_compute_minutes: float
    max_ram_mb: float
    max_disk_mb: float
    max_compute_minutes: float
    execution_location: str = "local"
    paid_api_used: bool = False
    cloud_fallback_used: bool = False


@dataclass(frozen=True)
class ResourceFeasibility:
    feasible: bool
    reasons: tuple[str, ...]
    envelope_digest: str
    proposal_only: bool = True


class Stage178ResourceGate:
    """Rejects work exceeding explicit local resource budgets; no paid/cloud fallback."""
    def assess(self, envelope: ResourceEnvelope, *, hold_active: bool = False) -> ResourceFeasibility:
        if hold_active:
            raise MergeReadinessError("HOLD blocks Stage 178")
        values = (envelope.measured_ram_mb, envelope.measured_disk_mb,
                  envelope.measured_compute_minutes, envelope.max_ram_mb,
                  envelope.max_disk_mb, envelope.max_compute_minutes)
        if not all(math.isfinite(x) and x >= 0 for x in values):
            raise MergeReadinessError("resource measurements and limits must be finite and non-negative")
        reasons = []
        if envelope.execution_location != "local":
            reasons.append("execution must remain local")
        if envelope.paid_api_used:
            reasons.append("paid API use is prohibited")
        if envelope.cloud_fallback_used:
            reasons.append("cloud fallback is prohibited")
        if envelope.measured_ram_mb > envelope.max_ram_mb:
            reasons.append("RAM budget exceeded")
        if envelope.measured_disk_mb > envelope.max_disk_mb:
            reasons.append("disk budget exceeded")
        if envelope.measured_compute_minutes > envelope.max_compute_minutes:
            reasons.append("compute-time budget exceeded")
        payload = {"measured": values[:3], "limits": values[3:],
                   "location": envelope.execution_location, "paid_api": envelope.paid_api_used,
                   "cloud_fallback": envelope.cloud_fallback_used, "reasons": reasons}
        return ResourceFeasibility(not reasons, tuple(reasons), _hash(payload))


@dataclass(frozen=True)
class HoldoutEvidence:
    manifest_digest: str
    holdout_suite_digest: str
    evaluator_id: str
    report_digest: str
    adversarial_cases: int
    passed_cases: int
    critical_failures: int
    signature: str


@dataclass(frozen=True)
class HoldoutAssessment:
    passed: bool
    evaluator_id: str
    pass_rate: float
    critical_failures: int
    assessment_digest: str
    proposal_only: bool = True


class Stage179HoldoutGate:
    """Requires signed, separate holdout evidence with zero critical failures."""
    def assess(self, manifest: MergeArtifactManifest, evidence: HoldoutEvidence, *,
               verify_signature: Callable[[HoldoutEvidence], bool],
               minimum_cases: int = 20, minimum_pass_rate: float = 0.98,
               hold_active: bool = False) -> HoldoutAssessment:
        if hold_active:
            raise MergeReadinessError("HOLD blocks Stage 179")
        if evidence.manifest_digest != manifest.manifest_digest:
            raise MergeReadinessError("holdout manifest lineage mismatch")
        _require_digest(evidence.holdout_suite_digest, "holdout suite")
        _require_digest(evidence.report_digest, "holdout report")
        if evidence.holdout_suite_digest == manifest.evaluation_suite_digest:
            raise MergeReadinessError("holdout suite must be separate from selection suite")
        if not _ID.fullmatch(evidence.evaluator_id or "") or not evidence.signature or len(evidence.signature) > 8192:
            raise MergeReadinessError("holdout evaluator identity or signature invalid")
        if not callable(verify_signature) or not verify_signature(evidence):
            raise MergeReadinessError("holdout signature verification failed")
        if (not isinstance(evidence.adversarial_cases, int) or isinstance(evidence.adversarial_cases, bool)
                or not isinstance(evidence.passed_cases, int) or isinstance(evidence.passed_cases, bool)
                or not isinstance(evidence.critical_failures, int) or isinstance(evidence.critical_failures, bool)
                or evidence.adversarial_cases < minimum_cases or not 0 <= evidence.passed_cases <= evidence.adversarial_cases
                or evidence.critical_failures < 0 or not 0 <= minimum_pass_rate <= 1):
            raise MergeReadinessError("holdout counts or thresholds invalid")
        rate = evidence.passed_cases / evidence.adversarial_cases
        passed = rate >= minimum_pass_rate and evidence.critical_failures == 0
        payload = {"manifest": manifest.manifest_digest, "suite": evidence.holdout_suite_digest,
                   "report": evidence.report_digest, "evaluator": evidence.evaluator_id,
                   "cases": evidence.adversarial_cases, "passed": evidence.passed_cases,
                   "critical": evidence.critical_failures, "pass_rate": rate, "result": passed}
        return HoldoutAssessment(passed, evidence.evaluator_id, rate,
                                 evidence.critical_failures, _hash(payload))


@dataclass(frozen=True)
class MergeApprovalPackage:
    manifest_digest: str
    reproducibility_report_digest: str
    resource_envelope_digest: str
    holdout_assessment_digest: str
    candidate_id: str
    proposed_generation: int
    readiness_digest: str
    ready_for_human_review: bool
    human_approval_required: bool = True
    human_approval_granted: bool = False
    merge_execution_authorized: bool = False
    weight_mutation_authorized: bool = False
    generation_advance_authorized: bool = False
    model_activation_authorized: bool = False
    production_switch_authorized: bool = False
    proposal_only: bool = True


class Stage180HumanApprovalPackager:
    """Packages evidence for a human decision; never grants approval or executes a merge."""
    def build(self, manifest: MergeArtifactManifest, reproducibility: ReproducibilityReport,
              resources: ResourceFeasibility, holdout: HoldoutAssessment, *,
              rollback_artifact_digest: str, hold_active: bool = False) -> MergeApprovalPackage:
        if hold_active:
            raise MergeReadinessError("HOLD blocks Stage 180")
        _require_digest(rollback_artifact_digest, "rollback artifact")
        if (reproducibility.manifest_digest != manifest.manifest_digest
                or not reproducibility.proposal_only
                or not resources.proposal_only
                or not holdout.proposal_only):
            raise MergeReadinessError("approval evidence lineage or authority mismatch")
        ready = reproducibility.reproducible and resources.feasible and holdout.passed
        payload = {"manifest": manifest.manifest_digest,
                   "reproducibility": reproducibility.report_digest,
                   "resources": resources.envelope_digest,
                   "holdout": holdout.assessment_digest,
                   "candidate": manifest.candidate_id,
                   "generation": manifest.proposed_generation,
                   "rollback": rollback_artifact_digest, "ready": ready}
        return MergeApprovalPackage(manifest.manifest_digest, reproducibility.report_digest,
                                    resources.envelope_digest, holdout.assessment_digest,
                                    manifest.candidate_id, manifest.proposed_generation,
                                    _hash(payload), ready)


__all__ = [
    "MergeReadinessError", "MergeArtifactManifest", "Stage176ArtifactManifestBuilder",
    "ReproducibilityEvidence", "ReproducibilityReport", "Stage177ReproducibilityVerifier",
    "ResourceEnvelope", "ResourceFeasibility", "Stage178ResourceGate",
    "HoldoutEvidence", "HoldoutAssessment", "Stage179HoldoutGate",
    "MergeApprovalPackage", "Stage180HumanApprovalPackager",
]
