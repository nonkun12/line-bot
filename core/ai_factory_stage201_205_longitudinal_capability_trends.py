"""Stages 201-205: longitudinal, evidence-bound capability trend assessment.

This module evaluates supplied signed measurement snapshots. It does not execute
models, establish hardware truth, or prove general intelligence/ASI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Callable, Sequence


_HEX = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")


class CapabilityTrendError(ValueError):
    """Raised when longitudinal evidence is invalid or insufficient."""


def _canonical_digest(payload: object) -> str:
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapabilityTrendError("payload is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise CapabilityTrendError(f"{label} is invalid")


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise CapabilityTrendError(f"{label} must be a lowercase SHA-256 digest")


def _signature(digest: str, signature: str,
               verifier: Callable[[str, str], bool], label: str) -> None:
    _sha(digest, label + " digest")
    if not isinstance(signature, str) or not signature or not callable(verifier):
        raise CapabilityTrendError(f"{label} signature/verifier missing")
    try:
        valid = verifier(digest, signature)
    except Exception as exc:
        raise CapabilityTrendError(f"{label} signature verification failed") from exc
    if valid is not True:
        raise CapabilityTrendError(f"{label} signature verification failed")


def _hold(active: bool, stage: int) -> None:
    if active:
        raise CapabilityTrendError(f"HOLD blocks Stage {stage}")


@dataclass(frozen=True)
class CapabilitySnapshot:
    snapshot_id: str
    candidate_id: str
    artifact_digest: str
    generation: int
    suite_digest: str
    dataset_digest: str
    environment_digest: str
    provenance_certificate_digest: str
    evaluator_id: str
    quality: float
    safety: float
    latency_ms: float
    memory_mb: float
    nonce: str
    snapshot_digest: str
    signature: str
    proposal_only: bool = True


def _snapshot_payload(*, snapshot_id: str, candidate_id: str, artifact_digest: str,
                      generation: int, suite_digest: str, dataset_digest: str,
                      environment_digest: str, provenance_certificate_digest: str,
                      evaluator_id: str, quality: float, safety: float,
                      latency_ms: float, memory_mb: float, nonce: str) -> dict:
    return {
        "snapshot_id": snapshot_id, "candidate_id": candidate_id,
        "artifact_digest": artifact_digest, "generation": generation,
        "suite_digest": suite_digest, "dataset_digest": dataset_digest,
        "environment_digest": environment_digest,
        "provenance_certificate_digest": provenance_certificate_digest,
        "evaluator_id": evaluator_id, "quality": quality, "safety": safety,
        "latency_ms": latency_ms, "memory_mb": memory_mb, "nonce": nonce,
        "proposal_only": True,
    }


class Stage201CapabilitySnapshot:
    """Create a signed, immutable measurement snapshot for one model generation."""

    def build(self, *, snapshot_id: str, candidate_id: str, artifact_digest: str,
              generation: int, suite_digest: str, dataset_digest: str,
              environment_digest: str, provenance_certificate_digest: str,
              evaluator_id: str, quality: float, safety: float, latency_ms: float,
              memory_mb: float, nonce: str,
              verify_provenance_certificate: Callable[[str], bool],
              sign: Callable[[str], str], verify: Callable[[str, str], bool],
              hold_active: bool = False) -> CapabilitySnapshot:
        _hold(hold_active, 201)
        for value, label in ((snapshot_id, "snapshot id"), (candidate_id, "candidate id"),
                             (evaluator_id, "evaluator id"), (nonce, "nonce")):
            _id(value, label)
        for value, label in (
            (artifact_digest, "artifact"), (suite_digest, "suite"),
            (dataset_digest, "dataset"), (environment_digest, "environment"),
            (provenance_certificate_digest, "provenance certificate"),
        ):
            _sha(value, label)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise CapabilityTrendError("generation must be a non-negative integer")
        for value, label in ((quality, "quality"), (safety, "safety")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise CapabilityTrendError(f"{label} must be finite and within [0, 1]")
        for value, label in ((latency_ms, "latency"), (memory_mb, "memory")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise CapabilityTrendError(f"{label} must be finite and positive")
        payload = _snapshot_payload(
            snapshot_id=snapshot_id, candidate_id=candidate_id,
            artifact_digest=artifact_digest, generation=generation,
            suite_digest=suite_digest, dataset_digest=dataset_digest,
            environment_digest=environment_digest,
            provenance_certificate_digest=provenance_certificate_digest,
            evaluator_id=evaluator_id, quality=float(quality), safety=float(safety),
            latency_ms=float(latency_ms), memory_mb=float(memory_mb), nonce=nonce,
        )
        digest = _canonical_digest(payload)
        if not callable(sign):
            raise CapabilityTrendError("snapshot signer missing")
        signature = sign(digest)
        _signature(digest, signature, verify, "snapshot")
        return CapabilitySnapshot(
            snapshot_id, candidate_id, artifact_digest, generation, suite_digest,
            dataset_digest, environment_digest, provenance_certificate_digest,
            evaluator_id, float(quality), float(safety), float(latency_ms),
            float(memory_mb), nonce, digest, signature,
        )


def verify_snapshot(snapshot: CapabilitySnapshot, *,
                    verify: Callable[[str, str], bool]) -> bool:
    if not isinstance(snapshot, CapabilitySnapshot) or snapshot.proposal_only is not True:
        return False
    payload = _snapshot_payload(
        snapshot_id=snapshot.snapshot_id, candidate_id=snapshot.candidate_id,
        artifact_digest=snapshot.artifact_digest, generation=snapshot.generation,
        suite_digest=snapshot.suite_digest, dataset_digest=snapshot.dataset_digest,
        environment_digest=snapshot.environment_digest,
        provenance_certificate_digest=snapshot.provenance_certificate_digest,
        evaluator_id=snapshot.evaluator_id, quality=snapshot.quality,
        safety=snapshot.safety, latency_ms=snapshot.latency_ms,
        memory_mb=snapshot.memory_mb, nonce=snapshot.nonce,
    )
    if _canonical_digest(payload) != snapshot.snapshot_digest:
        return False
    try:
        _signature(snapshot.snapshot_digest, snapshot.signature, verify, "snapshot")
    except CapabilityTrendError:
        return False
    return True


@dataclass(frozen=True)
class GenerationLineage:
    snapshot_digests: tuple[str, ...]
    generations: tuple[int, ...]
    lineage_digest: str
    signature: str
    proposal_only: bool = True


class Stage202GenerationLineage:
    """Verify an ordered, gap-free lineage of distinct candidate artifacts."""

    def build(self, snapshots: Sequence[CapabilitySnapshot], *,
              verify_snapshot_signature: Callable[[str, str], bool],
              sign: Callable[[str], str], verify: Callable[[str, str], bool],
              hold_active: bool = False) -> GenerationLineage:
        _hold(hold_active, 202)
        rows = tuple(snapshots)
        if len(rows) < 3:
            raise CapabilityTrendError("at least three generations are required")
        if any(not verify_snapshot(row, verify=verify_snapshot_signature) for row in rows):
            raise CapabilityTrendError("snapshot signature or digest invalid")
        generations = tuple(row.generation for row in rows)
        if any(b != a + 1 for a, b in zip(generations, generations[1:])):
            raise CapabilityTrendError("generations must be strictly consecutive")
        if len({row.snapshot_id for row in rows}) != len(rows):
            raise CapabilityTrendError("duplicate snapshot id")
        if len({row.artifact_digest for row in rows}) != len(rows):
            raise CapabilityTrendError("each generation must identify a distinct artifact")
        first = rows[0]
        for row in rows[1:]:
            if (row.suite_digest, row.dataset_digest, row.environment_digest) != (
                first.suite_digest, first.dataset_digest, first.environment_digest
            ):
                raise CapabilityTrendError("benchmark suite, dataset, and environment must remain fixed")
            if row.evaluator_id == first.evaluator_id:
                # Same evaluator is permitted only if the evaluator is explicitly independent
                # from every executor in the provenance certificate; that check is upstream.
                pass
        payload = {"snapshot_digests": [r.snapshot_digest for r in rows],
                   "generations": list(generations), "proposal_only": True}
        digest = _canonical_digest(payload)
        if not callable(sign):
            raise CapabilityTrendError("lineage signer missing")
        signature = sign(digest)
        _signature(digest, signature, verify, "lineage")
        return GenerationLineage(tuple(r.snapshot_digest for r in rows),
                                 generations, digest, signature)


@dataclass(frozen=True)
class CapabilityTrend:
    lineage_digest: str
    sample_count: int
    quality_gain: float
    safety_minimum: float
    safety_non_decreasing: bool
    latency_growth: float
    memory_growth: float
    supported: bool
    trend_digest: str
    signature: str
    proposal_only: bool = True


def _trend_payload(lineage_digest: str, sample_count: int, quality_gain: float,
                   safety_minimum: float, safety_non_decreasing: bool,
                   latency_growth: float, memory_growth: float,
                   supported: bool) -> dict:
    return {
        "lineage_digest": lineage_digest, "sample_count": sample_count,
        "quality_gain": quality_gain, "safety_minimum": safety_minimum,
        "safety_non_decreasing": safety_non_decreasing,
        "latency_growth": latency_growth, "memory_growth": memory_growth,
        "supported": supported, "proposal_only": True,
    }


class Stage203204TrendAnalyzer:
    """Compute a conservative trend under fixed-suite/data/environment conditions."""

    def build(self, snapshots: Sequence[CapabilitySnapshot],
              lineage: GenerationLineage, *,
              verify_lineage_signature: Callable[[str, str], bool],
              sign: Callable[[str], str], verify: Callable[[str, str], bool],
              hold_active: bool = False) -> CapabilityTrend:
        _hold(hold_active, 203)
        rows = tuple(snapshots)
        if len(rows) < 3 or len(rows) != len(lineage.snapshot_digests):
            raise CapabilityTrendError("insufficient or mismatched longitudinal samples")
        if tuple(r.snapshot_digest for r in rows) != lineage.snapshot_digests:
            raise CapabilityTrendError("snapshot sequence does not match lineage")
        payload = {"snapshot_digests": list(lineage.snapshot_digests),
                   "generations": list(lineage.generations), "proposal_only": True}
        if _canonical_digest(payload) != lineage.lineage_digest:
            raise CapabilityTrendError("lineage digest mismatch")
        _signature(lineage.lineage_digest, lineage.signature,
                    verify_lineage_signature, "lineage")
        if any(not verify_snapshot(row, verify=verify) for row in rows):
            raise CapabilityTrendError("snapshot invalid")
        baseline, latest = rows[0], rows[-1]
        quality_gain = latest.quality - baseline.quality
        safety_minimum = min(r.safety for r in rows)
        safety_non_decreasing = all(b.safety >= a.safety for a, b in zip(rows, rows[1:]))
        latency_growth = latest.latency_ms / baseline.latency_ms - 1.0
        memory_growth = latest.memory_mb / baseline.memory_mb - 1.0
        supported = (
            quality_gain >= 0.01 and safety_minimum >= 0.95
            and safety_non_decreasing and latency_growth <= 0.10
            and memory_growth <= 0.10
        )
        trend_payload = _trend_payload(
            lineage.lineage_digest, len(rows), quality_gain, safety_minimum,
            safety_non_decreasing, latency_growth, memory_growth, supported,
        )
        digest = _canonical_digest(trend_payload)
        signature = sign(digest)
        _signature(digest, signature, verify, "capability trend")
        return CapabilityTrend(
            lineage.lineage_digest, len(rows), quality_gain, safety_minimum,
            safety_non_decreasing, latency_growth, memory_growth, supported,
            digest, signature,
        )


@dataclass(frozen=True)
class RSITrendCertificate:
    status: str
    trend_digest: str
    lineage_digest: str
    sample_count: int
    certificate_digest: str
    signature: str
    proposal_only: bool = True
    model_activation_authorized: bool = False
    weight_mutation_authorized: bool = False
    merge_deploy_authorized: bool = False


class Stage205RSITrendGate:
    """Emit an evidence-qualified RSI trend signal, never an ASI claim."""

    def build(self, trend: CapabilityTrend, *,
              verify_trend_signature: Callable[[str, str], bool],
              sign: Callable[[str], str], verify: Callable[[str, str], bool],
              hold_active: bool = False) -> RSITrendCertificate:
        _hold(hold_active, 205)
        if not isinstance(trend, CapabilityTrend) or trend.proposal_only is not True:
            raise CapabilityTrendError("trend evidence invalid")
        payload = _trend_payload(
            trend.lineage_digest, trend.sample_count, trend.quality_gain,
            trend.safety_minimum, trend.safety_non_decreasing,
            trend.latency_growth, trend.memory_growth, trend.supported,
        )
        if _canonical_digest(payload) != trend.trend_digest:
            raise CapabilityTrendError("trend digest mismatch")
        _signature(trend.trend_digest, trend.signature,
                    verify_trend_signature, "trend")
        status = "CAPABILITY_TREND_SUPPORTED" if trend.supported else "INSUFFICIENT_OR_REGRESSING_EVIDENCE"
        cert_payload = {
            "status": status, "trend_digest": trend.trend_digest,
            "lineage_digest": trend.lineage_digest, "sample_count": trend.sample_count,
            "proposal_only": True, "model_activation_authorized": False,
            "weight_mutation_authorized": False, "merge_deploy_authorized": False,
        }
        digest = _canonical_digest(cert_payload)
        signature = sign(digest)
        _signature(digest, signature, verify, "RSI trend certificate")
        return RSITrendCertificate(status, trend.trend_digest, trend.lineage_digest,
                                   trend.sample_count, digest, signature)


def verify_rsi_trend_certificate(certificate: RSITrendCertificate, *,
                                 verify: Callable[[str, str], bool]) -> bool:
    if not isinstance(certificate, RSITrendCertificate):
        return False
    if (certificate.proposal_only is not True
            or certificate.model_activation_authorized is not False
            or certificate.weight_mutation_authorized is not False
            or certificate.merge_deploy_authorized is not False
            or certificate.status not in {"CAPABILITY_TREND_SUPPORTED",
                                          "INSUFFICIENT_OR_REGRESSING_EVIDENCE"}):
        return False
    payload = {
        "status": certificate.status, "trend_digest": certificate.trend_digest,
        "lineage_digest": certificate.lineage_digest, "sample_count": certificate.sample_count,
        "proposal_only": True, "model_activation_authorized": False,
        "weight_mutation_authorized": False, "merge_deploy_authorized": False,
    }
    if _canonical_digest(payload) != certificate.certificate_digest:
        return False
    try:
        _signature(certificate.certificate_digest, certificate.signature, verify, "RSI trend")
    except CapabilityTrendError:
        return False
    return True
