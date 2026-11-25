"""Fail-closed bridge from verified loop evidence to RSI measurements.

This module consumes already-produced evidence; it does not run tasks, alter
workflows, or authorize execution. Missing or mismatched evidence is rejected.
"""
from __future__ import annotations

import math
import re
from typing import Any

from core.self_improvement_measurement import SelfImprovementMeasurementRecord
from scripts.rea_control_tower_adapter import publish_row_has_valid_gates

_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_METRIC_FIELDS = frozenset({
    "schema_version", "metric_name", "metric_direction", "value",
    "sample_count", "target_sha", "task_id", "run_nonce", "evidence_id",
})


def _valid_metric_snapshot(
    snapshot: object,
    *,
    expected_sha: str,
    task_id: str,
    run_nonce: str,
) -> bool:
    if not isinstance(snapshot, dict) or set(snapshot) != _METRIC_FIELDS:
        return False
    value = snapshot.get("value")
    sample_count = snapshot.get("sample_count")
    return (
        type(snapshot.get("schema_version")) is int
        and snapshot["schema_version"] == 1
        and isinstance(snapshot.get("metric_name"), str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,99}", snapshot["metric_name"]) is not None
        and snapshot.get("metric_direction") in {"maximize", "minimize"}
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and type(sample_count) is int
        and 1 <= sample_count <= 1_000_000
        and snapshot.get("target_sha") == expected_sha
        and isinstance(snapshot.get("task_id"), str)
        and snapshot["task_id"] == task_id
        and isinstance(snapshot.get("run_nonce"), str)
        and snapshot["run_nonce"] == run_nonce
        and isinstance(snapshot.get("evidence_id"), str)
        and _EVIDENCE_ID.fullmatch(snapshot["evidence_id"]) is not None
    )


def verify_rsi_measurement_evidence(
    row: object,
    baseline: object,
    candidate: object,
) -> tuple[SelfImprovementMeasurementRecord | None, str]:
    """Return a measurement only when loop gates and both metric snapshots bind.

    The returned reason is a stable code suitable for diagnostics. A None record
    must remain INSUFFICIENT_EVIDENCE; callers must not infer missing values.
    """
    if not isinstance(row, dict):
        return None, "loop_row_invalid"
    base_sha = row.get("base_sha")
    produced_sha = row.get("produced_sha")
    task_id = row.get("task_id")
    run_nonce = row.get("run_nonce")
    if (
        not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha)
        or not isinstance(produced_sha, str) or not _SHA.fullmatch(produced_sha)
        or not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", task_id)
        or not isinstance(run_nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", run_nonce)
    ):
        return None, "loop_provenance_invalid"
    if not publish_row_has_valid_gates(row, expected_sha=base_sha):
        return None, "loop_safety_gates_not_verified"
    if not _valid_metric_snapshot(baseline, expected_sha=base_sha, task_id=task_id, run_nonce=run_nonce):
        return None, "baseline_metric_evidence_invalid"
    if not _valid_metric_snapshot(candidate, expected_sha=produced_sha, task_id=task_id, run_nonce=run_nonce):
        return None, "candidate_metric_evidence_invalid"
    assert isinstance(baseline, dict) and isinstance(candidate, dict)
    if (
        baseline["metric_name"] != candidate["metric_name"]
        or baseline["metric_direction"] != candidate["metric_direction"]
    ):
        return None, "metric_definition_mismatch"
    test_evidence = row.get("test_evidence")
    if (
        not isinstance(test_evidence, list)
        or not test_evidence
        or len(test_evidence) > 10
        or any(not isinstance(item, str) or not _EVIDENCE_ID.fullmatch(item) for item in test_evidence)
    ):
        return None, "test_evidence_missing_or_invalid"
    try:
        record = SelfImprovementMeasurementRecord(
            proposal_id=f"loop-{task_id}",
            metric_name=baseline["metric_name"],
            metric_direction=baseline["metric_direction"],
            baseline=baseline["value"],
            candidate=candidate["value"],
            base_sha=base_sha,
            produced_sha=produced_sha,
            test_evidence=tuple(test_evidence),
            safety_gate="PASS",
        )
    except (TypeError, ValueError):
        return None, "measurement_schema_invalid"
    # The current loop does not cryptographically attest metric artifact bytes.
    # Keep the measurement visible for diagnostics, but never label it improved.
    unattested = SelfImprovementMeasurementRecord(
        proposal_id=record.proposal_id,
        metric_name=record.metric_name,
        metric_direction=record.metric_direction,
        baseline=record.baseline,
        candidate=record.candidate,
        base_sha=record.base_sha,
        produced_sha=record.produced_sha,
        test_evidence=record.test_evidence,
        safety_gate="UNKNOWN",
    )
    return unattested, "metric_artifact_attestation_missing"


__all__ = ["verify_rsi_measurement_evidence"]
