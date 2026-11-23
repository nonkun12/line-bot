"""Stages 261-265: replication and evaluation-integrity controls.

All inputs are declarations supplied by callers. These stages improve structural
checks but do not authenticate external evaluators, task banks, environments, or
preregistration timestamps.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from collections.abc import Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_FALSE = {
    "proposal_only": True, "task_execution_authorized": False,
    "experiment_execution_authorized": False, "model_change_authorized": False,
    "merge_deploy_authorized": False, "hold_release_authorized": False,
}


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    body = {k: v for k, v in result.items() if k != "result_digest"}
    result["result_digest"] = sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return result


def _valid(result, expected_status):
    if not isinstance(result, Mapping) or result.get("status") != expected_status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    claimed = result.get("result_digest")
    if not _digest(claimed):
        return False
    try:
        body = {k: v for k, v in result.items() if k != "result_digest"}
        actual = sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        return False
    return claimed == actual


def stage261_validate_stratified_coverage(*, observations: Sequence[Mapping],
                                           preregistered_strata: Mapping,
                                           minimum_per_stratum: int = 5,
                                           held: bool = False):
    """Require observed paired-task coverage to meet each preregistered stratum quota."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(observations, Sequence) or isinstance(observations, (str, bytes))
            or not isinstance(preregistered_strata, Mapping) or not preregistered_strata
            or isinstance(minimum_per_stratum, bool) or not isinstance(minimum_per_stratum, int)
            or minimum_per_stratum < 1):
        return _blocked("observations, strata quotas and positive minimum are required")
    quotas = {}
    for key, quota in preregistered_strata.items():
        if (not isinstance(key, str) or not key.strip() or isinstance(quota, bool)
                or not isinstance(quota, int) or quota < minimum_per_stratum):
            return _blocked("each stratum needs a valid quota at or above the minimum")
        quotas[key] = quota
    counts = {key: 0 for key in quotas}
    seen = set()
    for row in observations:
        if not isinstance(row, Mapping):
            return _blocked("each observation must be a mapping")
        task_id, stratum = row.get("task_id"), row.get("stratum")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen or stratum not in counts:
            return _blocked("duplicate task or unregistered stratum")
        seen.add(task_id)
        counts[stratum] += 1
    if any(counts[key] < quota for key, quota in quotas.items()):
        return _blocked("one or more strata fail preregistered coverage quotas")
    return _seal({
        "status": "STRATIFIED_COVERAGE_VALIDATED",
        "strata_counts": counts, "strata_quotas": quotas,
        "task_count": len(seen),
    })


def stage262_validate_environment_parity(*, baseline_manifest: Mapping,
                                          candidate_manifest: Mapping,
                                          required_fields=("runtime_digest", "hardware_class",
                                                           "precision", "sampling_config_digest",
                                                           "resource_budget_digest"),
                                          held: bool = False):
    """Require baseline/candidate environment manifests to match on required fields."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(baseline_manifest, Mapping) or not isinstance(candidate_manifest, Mapping)
            or not isinstance(required_fields, Sequence) or isinstance(required_fields, (str, bytes))
            or not required_fields):
        return _blocked("two manifests and required field list are required")
    fields = tuple(required_fields)
    if (any(not isinstance(field, str) or not field.strip() for field in fields)
            or len(set(fields)) != len(fields)):
        return _blocked("required fields must be unique non-empty strings")
    baseline, candidate = {}, {}
    for field in fields:
        left, right = baseline_manifest.get(field), candidate_manifest.get(field)
        if left is None or right is None or left != right:
            return _blocked("environment parity missing or mismatch: " + field)
        if not isinstance(left, (str, int, float, bool)):
            return _blocked("environment fields must be scalar declarations")
        if isinstance(left, float) and not math.isfinite(left):
            return _blocked("environment fields cannot contain non-finite values")
        baseline[field] = left
        candidate[field] = right
    canonical = json.dumps(baseline, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return _seal({
        "status": "ENVIRONMENT_PARITY_DECLARED",
        "environment_digest": sha256(canonical.encode()).hexdigest(),
        "matched_fields": list(fields),
    })


def stage263_validate_contamination_screen(*, task_records: Sequence[Mapping],
                                           evaluator_id: str, model_operator_id: str,
                                           held: bool = False):
    """Require per-task screening records, evidence digests and evaluator/operator separation."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_records, Sequence) or isinstance(task_records, (str, bytes))
            or not task_records or not isinstance(evaluator_id, str) or not evaluator_id.strip()
            or not isinstance(model_operator_id, str) or not model_operator_id.strip()
            or evaluator_id == model_operator_id):
        return _blocked("task screening records and distinct evaluator/operator IDs are required")
    seen, normalized = set(), []
    for row in task_records:
        if not isinstance(row, Mapping):
            return _blocked("each contamination record must be a mapping")
        task_id, evidence_digest, outcome = row.get("task_id"), row.get("screening_evidence_digest"), row.get("outcome")
        if (not isinstance(task_id, str) or not task_id.strip() or task_id in seen
                or not _digest(evidence_digest) or outcome != "no_known_contamination"):
            return _blocked("missing, duplicate, invalid or flagged contamination record")
        seen.add(task_id)
        normalized.append({"task_id": task_id, "screening_evidence_digest": evidence_digest})
    normalized.sort(key=lambda row: row["task_id"])
    return _seal({
        "status": "CONTAMINATION_SCREEN_DECLARED_CLEAR",
        "task_count": len(normalized), "evaluator_id": evaluator_id,
        "model_operator_id": model_operator_id,
        "screening_digest": sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    })


def stage264_correct_multiple_comparisons(*, estimates: Sequence[Mapping],
                                          family_alpha: float = 0.05,
                                          held: bool = False):
    """Apply Bonferroni-adjusted lower-bound checks to a fixed family of estimates."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(estimates, Sequence) or isinstance(estimates, (str, bytes))
            or not estimates or isinstance(family_alpha, bool)
            or not isinstance(family_alpha, (int, float)) or not math.isfinite(family_alpha)
            or not 0 < family_alpha < 0.5):
        return _blocked("a non-empty estimate family and valid family alpha are required")
    count = len(estimates)
    alpha_each = family_alpha / count
    rows = []
    for estimate in estimates:
        if not isinstance(estimate, Mapping) or estimate.get("status") != "PAIRED_GAIN_ESTIMATED":
            return _blocked("every family member must be a paired gain estimate")
        claimed = estimate.get("result_digest")
        try:
            estimate_body = {key: value for key, value in estimate.items() if key != "result_digest"}
            actual = sha256(json.dumps(estimate_body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError):
            return _blocked("estimate digest cannot be recomputed")
        if (not _digest(claimed) or claimed != actual
                or not _digest(estimate.get("protocol_digest"))
                or not _digest(estimate.get("observations_digest"))
                or isinstance(estimate.get("sample_count"), bool)
                or not isinstance(estimate.get("sample_count"), int) or estimate["sample_count"] < 1
                or not isinstance(estimate.get("mean_gain"), (int, float))
                or not isinstance(estimate.get("lower_bound"), (int, float))
                or not math.isfinite(estimate["mean_gain"]) or not math.isfinite(estimate["lower_bound"])):
            return _blocked("malformed estimate")
        n = estimate["sample_count"]
        radius = math.sqrt(2.0 * math.log(2.0 / alpha_each) / n)
        lower = max(-1.0, estimate["mean_gain"] - radius)
        rows.append({
            "protocol_digest": estimate["protocol_digest"],
            "observations_digest": estimate["observations_digest"],
            "sample_count": n, "mean_gain": estimate["mean_gain"],
            "adjusted_lower_bound": lower,
        })
    rows.sort(key=lambda row: (row["protocol_digest"], row["observations_digest"]))
    return _seal({
        "status": "MULTIPLE_COMPARISON_CORRECTION_APPLIED",
        "family_size": count, "family_alpha": float(family_alpha),
        "per_comparison_alpha": alpha_each, "method": "Bonferroni",
        "estimates": rows,
    })


def stage265_validate_independent_replication(*, primary_preregistration: Mapping,
                                               replication_preregistration: Mapping,
                                               primary_package: Mapping,
                                               replication_package: Mapping,
                                               primary_evaluator_id: str,
                                               replication_evaluator_id: str,
                                               held: bool = False):
    """Require positive gated evidence on distinct task sets and declared evaluators."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not _valid(primary_preregistration, "EVALUATION_PREREGISTERED")
            or not _valid(replication_preregistration, "EVALUATION_PREREGISTERED")
            or not _valid(primary_package, "CAPABILITY_EVIDENCE_PACKAGE_READY")
            or not _valid(replication_package, "CAPABILITY_EVIDENCE_PACKAGE_READY")):
        return _blocked("both preregistrations and evidence packages must pass integrity validation")
    if (not isinstance(primary_evaluator_id, str) or not primary_evaluator_id.strip()
            or not isinstance(replication_evaluator_id, str) or not replication_evaluator_id.strip()
            or primary_evaluator_id == replication_evaluator_id):
        return _blocked("independent evaluator IDs must be distinct declarations")
    primary_protocol = dict(primary_preregistration["protocol"])
    replication_protocol = dict(replication_preregistration["protocol"])
    primary_task_set = primary_protocol.pop("task_set_digest", None)
    replication_task_set = replication_protocol.pop("task_set_digest", None)
    if primary_task_set == replication_task_set:
        return _blocked("replication must use a distinct task set")
    if primary_protocol != replication_protocol:
        return _blocked("replication protocol parameters must match apart from task-set identity")
    if (primary_package["protocol_digest"] != primary_preregistration["protocol_digest"]
            or replication_package["protocol_digest"] != replication_preregistration["protocol_digest"]
            or primary_package["task_set_digest"] != primary_task_set
            or replication_package["task_set_digest"] != replication_task_set):
        return _blocked("package-to-preregistration linkage mismatch")
    if (primary_package["gate_status"] != "CAPABILITY_GAIN_SUPPORTED"
            or replication_package["gate_status"] != "CAPABILITY_GAIN_SUPPORTED"):
        return _blocked("both primary and replication gates must support the gain")
    family_digest = sha256(json.dumps(primary_protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return _seal({
        "status": "INDEPENDENT_REPLICATION_DECLARED",
        "protocol_family_digest": family_digest,
        "primary_task_set_digest": primary_package["task_set_digest"],
        "replication_task_set_digest": replication_package["task_set_digest"],
        "primary_evaluator_id": primary_evaluator_id,
        "replication_evaluator_id": replication_evaluator_id,
        "requires_external_audit": True,
        "rsi_or_asi_demonstrated": False,
    })
