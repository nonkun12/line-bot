"""Stages 791-800: independent evaluation evidence and fail-closed gating.

This module validates caller-supplied records. It does not authenticate people,
execute benchmarks, fetch artifacts, or certify general intelligence.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
from typing import Any, Iterable


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_record(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


@dataclass(frozen=True)
class VerificationResult:
    status: str
    reasons: tuple[str, ...]
    evidence_digest: str | None = None
    stages: tuple[int, ...] = tuple(range(791, 801))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def validate_evaluator_attestation(record: dict[str, Any]) -> list[str]:
    errors = []
    required = ("evaluator_id", "organization", "conflict_declaration",
                "scope", "issued_at", "evidence_digest")
    for key in required:
        if not record.get(key):
            errors.append("attestation_missing_" + key)
    if record.get("conflict_declaration") not in ("none_declared", "conflict_declared"):
        errors.append("attestation_invalid_conflict_declaration")
    if record.get("scope") != "independent_evaluation":
        errors.append("attestation_scope_mismatch")
    if not _is_digest(record.get("evidence_digest")):
        errors.append("attestation_invalid_evidence_digest")
    return errors


def validate_reproduction_receipt(receipt: dict[str, Any],
                                  expected_manifest_digest: str) -> list[str]:
    errors = []
    if receipt.get("manifest_digest") != expected_manifest_digest:
        errors.append("reproduction_manifest_mismatch")
    if receipt.get("status") != "completed":
        errors.append("reproduction_not_completed")
    if not receipt.get("environment_fingerprint"):
        errors.append("reproduction_environment_missing")
    if not _is_digest(receipt.get("output_digest")):
        errors.append("reproduction_output_digest_invalid")
    if not isinstance(receipt.get("exit_code"), int) or receipt.get("exit_code") != 0:
        errors.append("reproduction_exit_code_not_zero")
    if not receipt.get("started_at") or not receipt.get("finished_at"):
        errors.append("reproduction_timestamps_missing")
    return errors


def compare_metric_sets(baseline: dict[str, Any], candidate: dict[str, Any],
                        directions: dict[str, str]) -> tuple[list[str], dict[str, float]]:
    errors: list[str] = []
    deltas: dict[str, float] = {}
    if set(baseline) != set(candidate) or set(baseline) != set(directions):
        return ["metric_keys_mismatch"], deltas
    for key in sorted(baseline):
        before, after = baseline[key], candidate[key]
        if (isinstance(before, bool) or isinstance(after, bool)
                or not isinstance(before, (int, float))
                or not isinstance(after, (int, float))
                or not math.isfinite(before) or not math.isfinite(after)):
            errors.append("metric_non_finite_or_non_numeric:" + key)
            continue
        direction = directions[key]
        if direction not in ("higher", "lower", "neutral"):
            errors.append("metric_direction_invalid:" + key)
            continue
        deltas[key] = float(after - before)
    return errors, deltas


def evaluate_stages_791_800(*, manifest: dict[str, Any],
                            artifacts: dict[str, bytes],
                            attestation: dict[str, Any],
                            reproduction: dict[str, Any],
                            baseline_metrics: dict[str, Any],
                            candidate_metrics: dict[str, Any],
                            metric_directions: dict[str, str],
                            independent_review: dict[str, Any]) -> VerificationResult:
    """791 manifest; 792 artifact digests; 793 provenance; 794 attestation;
    795 reproduction; 796 environment; 797 metrics; 798 independent review;
    799 integrated report; 800 fail-closed gate.
    """
    errors: list[str] = []
    declared = manifest.get("artifacts")
    if not isinstance(declared, dict) or not declared:
        errors.append("manifest_artifacts_missing")
        declared = {}
    if set(declared) != set(artifacts):
        errors.append("artifact_inventory_mismatch")
    for name, expected in declared.items():
        if name in artifacts and (not _is_digest(expected)
                                   or sha256_bytes(artifacts[name]) != expected):
            errors.append("artifact_digest_mismatch:" + str(name))

    manifest_digest = digest_record(manifest)
    if manifest.get("schema_version") != "1":
        errors.append("manifest_schema_unsupported")
    if not manifest.get("run_id") or not manifest.get("source_revision"):
        errors.append("manifest_provenance_incomplete")

    errors.extend(validate_evaluator_attestation(attestation))
    if attestation.get("evidence_digest") != manifest_digest:
        errors.append("attestation_manifest_binding_mismatch")
    errors.extend(validate_reproduction_receipt(reproduction, manifest_digest))
    metric_errors, deltas = compare_metric_sets(
        baseline_metrics, candidate_metrics, metric_directions)
    errors.extend(metric_errors)

    # Independence is a declaration, not authenticated identity proof.
    if independent_review.get("status") != "reviewed":
        errors.append("independent_review_incomplete")
    if independent_review.get("evidence_digest") != manifest_digest:
        errors.append("independent_review_manifest_mismatch")
    if independent_review.get("conflict_declaration") != "none_declared":
        errors.append("independent_review_conflict_or_missing")
    if independent_review.get("reviewer_id") == attestation.get("evaluator_id"):
        errors.append("evaluator_and_reviewer_not_distinct")

    report = {
        "manifest_digest": manifest_digest,
        "artifact_count": len(artifacts),
        "reproduction_status": reproduction.get("status"),
        "metric_deltas": deltas,
        "review_status": independent_review.get("status"),
        "errors": sorted(set(errors)),
    }
    status = "READY_FOR_EXTERNAL_AUTHENTICATED_REVIEW" if not errors else "BLOCKED"
    return VerificationResult(status, tuple(report["errors"]), digest_record(report))


__all__ = [
    "VerificationResult", "canonical_json", "sha256_bytes", "digest_record",
    "validate_evaluator_attestation", "validate_reproduction_receipt",
    "compare_metric_sets", "evaluate_stages_791_800",
]
