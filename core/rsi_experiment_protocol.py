"""Pure, read-only protocol for safe Recursive Self-Improvement comparisons.

This module never runs candidates, changes files, clears HOLD/STOP, or authorizes
execution. A PASS means only that a Challenger beat its Baseline on a locked
held-out dataset under an independent evaluator.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPERIMENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _blocked(experiment_id: str, reason: str) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "status": "BLOCKED",
        "reason": reason,
        "improvement": None,
        "evidence_sha256": None,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "stop_clear_authorized": False,
        "merge_deploy_authorized": False,
        "required_human_approval": True,
    }


def evaluate_comparison(record: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate supplied scores only; never execute or modify either candidate.

    Required record keys:
      experiment_id, baseline, challenger, evaluator, held_out, safety

    baseline/challenger contain candidate_id, artifact_sha256, score.
    evaluator contains evaluator_id, version, metric, direction, minimum_delta.
    held_out contains dataset_id, dataset_sha256, sample_count, locked=True.
    safety contains stop_state=INACTIVE and global_hold_state=CLEAR.
    """
    if not isinstance(record, Mapping):
        return _blocked("", "record_must_be_object")

    experiment_id = record.get("experiment_id")
    if not isinstance(experiment_id, str) or not _EXPERIMENT_ID.fullmatch(experiment_id):
        return _blocked("", "invalid_experiment_id")

    baseline = record.get("baseline")
    challenger = record.get("challenger")
    evaluator = record.get("evaluator")
    held_out = record.get("held_out")
    safety = record.get("safety")
    if not all(isinstance(item, Mapping) for item in (baseline, challenger, evaluator, held_out, safety)):
        return _blocked(experiment_id, "required_section_missing_or_invalid")

    baseline_id = baseline.get("candidate_id")
    challenger_id = challenger.get("candidate_id")
    evaluator_id = evaluator.get("evaluator_id")
    if not all(isinstance(item, str) and item.strip() for item in (baseline_id, challenger_id, evaluator_id)):
        return _blocked(experiment_id, "candidate_or_evaluator_identity_invalid")
    if baseline_id == challenger_id or evaluator_id in {baseline_id, challenger_id}:
        return _blocked(experiment_id, "evaluator_must_be_independent")

    for candidate in (baseline, challenger):
        digest = candidate.get("artifact_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            return _blocked(experiment_id, "candidate_artifact_digest_invalid")
        if not _finite_number(candidate.get("score")):
            return _blocked(experiment_id, "candidate_score_invalid")

    dataset_id = held_out.get("dataset_id")
    dataset_digest = held_out.get("dataset_sha256")
    sample_count = held_out.get("sample_count")
    if (
        not isinstance(dataset_id, str)
        or not dataset_id.strip()
        or not isinstance(dataset_digest, str)
        or not _SHA256.fullmatch(dataset_digest)
        or not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count <= 0
        or held_out.get("locked") is not True
    ):
        return _blocked(experiment_id, "held_out_dataset_not_locked_or_invalid")

    metric = evaluator.get("metric")
    version = evaluator.get("version")
    direction = evaluator.get("direction")
    minimum_delta = evaluator.get("minimum_delta")
    if (
        not isinstance(metric, str)
        or not metric.strip()
        or not isinstance(version, str)
        or not version.strip()
        or direction not in {"higher", "lower"}
        or not _finite_number(minimum_delta)
        or float(minimum_delta) < 0
    ):
        return _blocked(experiment_id, "evaluator_configuration_invalid")

    if safety.get("stop_state") != "INACTIVE":
        return _blocked(experiment_id, "stop_active_or_unverified")
    if safety.get("global_hold_state") != "CLEAR":
        return _blocked(experiment_id, "global_hold_active_or_unverified")

    baseline_score = float(baseline["score"])
    challenger_score = float(challenger["score"])
    improvement = (
        challenger_score - baseline_score
        if direction == "higher"
        else baseline_score - challenger_score
    )
    status = "PASS" if improvement > 0 and improvement >= float(minimum_delta) else "FAIL"

    canonical = json.dumps(
        dict(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    evidence_sha256 = hashlib.sha256(canonical).hexdigest()
    return {
        "experiment_id": experiment_id,
        "status": status,
        "reason": "challenger_improved_on_locked_holdout" if status == "PASS" else "minimum_improvement_not_met",
        "metric": metric,
        "direction": direction,
        "baseline_score": baseline_score,
        "challenger_score": challenger_score,
        "improvement": improvement,
        "held_out_dataset_id": dataset_id,
        "held_out_dataset_sha256": dataset_digest,
        "evaluator_id": evaluator_id,
        "evaluator_version": version,
        "evidence_sha256": evidence_sha256,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "stop_clear_authorized": False,
        "merge_deploy_authorized": False,
        "required_human_approval": True,
    }
