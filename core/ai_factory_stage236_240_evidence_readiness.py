"""Stages 236-240: corroboration, evaluator drift, preregistration, retention and readiness.

Deterministic proposal-only evidence governance. No experiment or task is run.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
import re
from typing import Mapping, Sequence


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _blocked(reason: str) -> dict:
    return {
        "status": "INSUFFICIENT_EVIDENCE",
        "reason": reason,
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
        "hold_release_authorized": False,
    }


def _aware(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _digest(value):
    return isinstance(value, str) and _DIGEST_RE.fullmatch(value) is not None


def _finite_unit_metrics(metrics):
    if not isinstance(metrics, Mapping) or not metrics:
        return False
    return all(
        isinstance(key, str) and key.strip()
        and isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and 0.0 <= value <= 1.0
        for key, value in metrics.items()
    )


def _proposal_only(payload: dict) -> dict:
    payload.update({
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
        "hold_release_authorized": False,
    })
    return payload


def stage236_independent_source_corroboration(
    *, observations: Sequence[Mapping], minimum_sources: int = 2, held: bool = False
):
    """Require independent source IDs to report the same digest per evidence ID."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(minimum_sources, int) or isinstance(minimum_sources, bool)
            or minimum_sources < 2 or not isinstance(observations, Sequence)
            or isinstance(observations, (str, bytes)) or not observations):
        return _blocked("invalid corroboration inputs")
    grouped = {}
    seen_pairs = set()
    for item in observations:
        if not isinstance(item, Mapping):
            return _blocked("observation must be a mapping")
        evidence_id, source_id, digest = (
            item.get("evidence_id"), item.get("source_id"), item.get("digest")
        )
        if not all(isinstance(x, str) and x.strip() for x in (evidence_id, source_id)):
            return _blocked("evidence and source IDs are required")
        if not _digest(digest):
            return _blocked("invalid evidence digest")
        pair = (evidence_id.strip(), source_id.strip())
        if pair in seen_pairs:
            return _blocked("duplicate evidence/source observation")
        seen_pairs.add(pair)
        grouped.setdefault(pair[0], []).append((pair[1], digest))
    insufficient = []
    conflicts = []
    for evidence_id, rows in grouped.items():
        if len({source for source, _ in rows}) < minimum_sources:
            insufficient.append(evidence_id)
        if len({digest for _, digest in rows}) != 1:
            conflicts.append(evidence_id)
    status = "SOURCES_CORROBORATED" if not insufficient and not conflicts else "CORROBORATION_FAILED"
    return _proposal_only({
        "status": status,
        "evidence_count": len(grouped),
        "minimum_sources": minimum_sources,
        "insufficient_evidence_ids": sorted(insufficient),
        "conflicting_evidence_ids": sorted(conflicts),
        "source_counts": {key: len({source for source, _ in rows}) for key, rows in grouped.items()},
    })


def stage237_evaluator_drift(
    *, baseline_metrics: Mapping, current_metrics: Mapping,
    evaluator_id: str, expected_evaluator_id: str,
    sample_count: int, minimum_samples: int = 20,
    max_abs_drift: float = 0.05, held: bool = False,
):
    """Compare bounded calibration metrics for the same declared evaluator."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(evaluator_id, str) or not evaluator_id.strip()
            or evaluator_id != expected_evaluator_id):
        return _blocked("evaluator identity mismatch")
    if (not isinstance(sample_count, int) or isinstance(sample_count, bool)
            or not isinstance(minimum_samples, int) or isinstance(minimum_samples, bool)
            or minimum_samples < 1 or sample_count < minimum_samples):
        return _blocked("insufficient calibration sample count")
    if (not isinstance(max_abs_drift, (int, float)) or isinstance(max_abs_drift, bool)
            or not math.isfinite(max_abs_drift) or not 0 <= max_abs_drift <= 1):
        return _blocked("invalid drift threshold")
    if (not _finite_unit_metrics(baseline_metrics) or not _finite_unit_metrics(current_metrics)
            or set(baseline_metrics) != set(current_metrics)):
        return _blocked("invalid or incomparable calibration metrics")
    deltas = {key: abs(current_metrics[key] - baseline_metrics[key]) for key in baseline_metrics}
    maximum = max(deltas.values())
    return _proposal_only({
        "status": "EVALUATOR_STABLE" if maximum <= max_abs_drift else "EVALUATOR_DRIFT_DETECTED",
        "evaluator_id": evaluator_id,
        "sample_count": sample_count,
        "metric_deltas": deltas,
        "max_abs_drift": max_abs_drift,
        "observed_max_abs_drift": maximum,
        "calibration_only": True,
    })


def stage238_validate_preregistration(
    *, protocol: Mapping, registered_at: str, held: bool = False
):
    """Validate a frozen experiment plan before any outcomes are observed."""
    if held:
        return _blocked("HOLD is active")
    required_text = (
        "hypothesis", "primary_metric", "dataset_digest", "suite_digest",
        "analysis_plan", "randomization_method",
    )
    if not isinstance(protocol, Mapping):
        return _blocked("protocol is missing or invalid")
    if any(not isinstance(protocol.get(key), str) or not protocol[key].strip()
           for key in required_text):
        return _blocked("required preregistration fields are missing")
    if not _digest(protocol.get("dataset_digest")) or not _digest(protocol.get("suite_digest")):
        return _blocked("dataset or suite digest is invalid")
    threshold = protocol.get("success_threshold")
    sample_size = protocol.get("sample_size")
    guardrails = protocol.get("safety_guardrails")
    if (not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
            or not math.isfinite(threshold)):
        return _blocked("success threshold must be finite")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 2:
        return _blocked("sample size must be an integer of at least two")
    if not isinstance(guardrails, Mapping) or not guardrails:
        return _blocked("explicit safety guardrails are required")
    if any(not isinstance(k, str) or not k.strip() or v is None for k, v in guardrails.items()):
        return _blocked("safety guardrails contain invalid entries")
    timestamp = _aware(registered_at)
    if timestamp is None:
        return _blocked("registration timestamp must be timezone-aware")
    if protocol.get("outcomes_observed") is not False:
        return _blocked("preregistration must precede outcome observation")
    canonical = json.dumps(dict(protocol), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return _proposal_only({
        "status": "PREREGISTRATION_VALID",
        "protocol_digest": sha256(canonical.encode("utf-8")).hexdigest(),
        "registered_at": timestamp.isoformat(),
        "sample_size": sample_size,
        "primary_metric": protocol["primary_metric"],
        "outcomes_observed": False,
    })


def stage239_build_retention_manifest(
    *, artifacts: Sequence[Mapping], evaluated_at: str, held: bool = False
):
    """Validate a durable provenance/retention inventory and hash its canonical form."""
    if held:
        return _blocked("HOLD is active")
    now = _aware(evaluated_at)
    if now is None or not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)) or not artifacts:
        return _blocked("invalid evaluation timestamp or empty artifact inventory")
    normalized = []
    seen = set()
    for item in artifacts:
        if not isinstance(item, Mapping):
            return _blocked("artifact entry must be a mapping")
        artifact_id, digest, provenance = (
            item.get("artifact_id"), item.get("digest"), item.get("provenance_ref")
        )
        created, retain_until = _aware(item.get("created_at")), _aware(item.get("retain_until"))
        if (not isinstance(artifact_id, str) or not artifact_id.strip()
                or artifact_id in seen or not _digest(digest)
                or not isinstance(provenance, str) or not provenance.strip()
                or created is None or retain_until is None):
            return _blocked("artifact identity, digest, provenance or timestamps are invalid")
        if created > now or retain_until <= now or retain_until <= created:
            return _blocked("artifact timestamp or retention window is invalid")
        seen.add(artifact_id)
        normalized.append({
            "artifact_id": artifact_id,
            "digest": digest,
            "provenance_ref": provenance,
            "created_at": created.isoformat(),
            "retain_until": retain_until.isoformat(),
        })
    normalized.sort(key=lambda row: row["artifact_id"])
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return _proposal_only({
        "status": "RETENTION_MANIFEST_VALID",
        "artifact_count": len(normalized),
        "manifest_digest": sha256(canonical.encode("utf-8")).hexdigest(),
        "retention_checked_at": now.isoformat(),
        "artifacts": normalized,
    })


def stage240_readiness_summary(
    *, corroboration: Mapping, evaluator: Mapping,
    preregistration: Mapping, retention: Mapping, held: bool = False,
):
    """Summarize evidence readiness without granting authority or claiming RSI progress."""
    if held:
        return _blocked("HOLD is active")
    required = {
        "corroboration": (corroboration, "SOURCES_CORROBORATED"),
        "evaluator": (evaluator, "EVALUATOR_STABLE"),
        "preregistration": (preregistration, "PREREGISTRATION_VALID"),
        "retention": (retention, "RETENTION_MANIFEST_VALID"),
    }
    failed = [
        name for name, (result, expected) in required.items()
        if not isinstance(result, Mapping) or result.get("status") != expected
    ]
    return _proposal_only({
        "status": "EVIDENCE_READY_FOR_SEPARATE_REVIEW" if not failed else "READINESS_BLOCKED",
        "failed_gates": failed,
        "passed_gates": [name for name in required if name not in failed],
        "required_next_step": "independent review and separate explicit authorization" if not failed else "resolve evidence gaps; do not execute",
        "authority": "readiness summary only; no execution or state-transition authority",
        "asi_or_rsi_claim": False,
    })
