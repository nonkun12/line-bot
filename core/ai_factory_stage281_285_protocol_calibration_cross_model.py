"""Stages 281-285: protocol integrity, evaluator calibration and cross-model checks.

All identities, task declarations, scores and evidence digests are caller-supplied.
These stages validate declared evidence structure; they do not authenticate execution,
prove evaluator independence, or authorize experiments/model changes.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math

_FALSE = {
    "proposal_only": True,
    "task_execution_authorized": False,
    "experiment_execution_authorized": False,
    "model_change_authorized": False,
    "merge_deploy_authorized": False,
    "hold_release_authorized": False,
}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _valid(result, expected):
    if not isinstance(result, Mapping) or result.get("status") != expected:
        return False
    if any(result.get(key) is not value for key, value in _FALSE.items()):
        return False
    try:
        return _digest(result.get("result_digest")) and result["result_digest"] == _hash(
            {key: value for key, value in result.items() if key != "result_digest"}
        )
    except (TypeError, ValueError):
        return False


def stage281_detect_protocol_drift(*, preregistered_protocol: Mapping,
                                   observed_protocol: Mapping, held: bool = False):
    """Compare canonical protocol snapshots; any mismatch is a drift failure."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(preregistered_protocol, Mapping) or not isinstance(observed_protocol, Mapping):
        return _blocked("both protocol snapshots must be mappings")
    if not preregistered_protocol or not observed_protocol:
        return _blocked("protocol snapshots must be non-empty")
    try:
        expected_digest, observed_digest = _hash(preregistered_protocol), _hash(observed_protocol)
    except (TypeError, ValueError):
        return _blocked("protocol snapshots must contain canonical JSON values")
    matches = expected_digest == observed_digest
    return _seal({
        "status": "PROTOCOL_UNCHANGED" if matches else "PROTOCOL_DRIFT_DETECTED",
        "preregistered_protocol_digest": expected_digest,
        "observed_protocol_digest": observed_digest,
        "protocol_match": matches,
        "trusted_preregistration_time_verified": False,
    })


def stage282_calibrate_evaluators(*, calibration_rows: Sequence[Mapping],
                                  maximum_mean_absolute_error: float = 0.10,
                                  maximum_single_error: float = 0.20,
                                  minimum_items_per_evaluator: int = 3,
                                  held: bool = False):
    """Calibrate declared evaluator scores against supplied reference scores."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(calibration_rows, Sequence) or isinstance(calibration_rows, (str, bytes))
            or isinstance(minimum_items_per_evaluator, bool)
            or not isinstance(minimum_items_per_evaluator, int) or minimum_items_per_evaluator < 3
            or not _number(maximum_mean_absolute_error) or not 0 <= maximum_mean_absolute_error <= 1
            or not _number(maximum_single_error) or not 0 <= maximum_single_error <= 1):
        return _blocked("calibration rows and thresholds are invalid")
    grouped, seen = {}, set()
    for row in calibration_rows:
        if not isinstance(row, Mapping):
            return _blocked("each calibration row must be a mapping")
        evaluator, item = row.get("evaluator_id"), row.get("item_id")
        score, reference, evidence = row.get("score"), row.get("reference_score"), row.get("evidence_digest")
        if (not isinstance(evaluator, str) or not evaluator.strip()
                or not isinstance(item, str) or not item.strip()
                or (evaluator, item) in seen
                or not _number(score) or not 0 <= score <= 1
                or not _number(reference) or not 0 <= reference <= 1 or not _digest(evidence)):
            return _blocked("calibration identity, score, reference or evidence is invalid")
        seen.add((evaluator, item))
        grouped.setdefault(evaluator, []).append(abs(float(score) - float(reference)))
    if not grouped or any(len(errors) < minimum_items_per_evaluator for errors in grouped.values()):
        return _blocked("each evaluator must meet the minimum calibration item count")
    summaries, failed = [], []
    for evaluator, errors in sorted(grouped.items()):
        mean_error, max_error = sum(errors) / len(errors), max(errors)
        summaries.append({"evaluator_id": evaluator, "item_count": len(errors),
                          "mean_absolute_error": mean_error, "maximum_absolute_error": max_error})
        if mean_error > maximum_mean_absolute_error or max_error > maximum_single_error:
            failed.append(evaluator)
    return _seal({
        "status": "EVALUATORS_CALIBRATED" if not failed else "EVALUATOR_CALIBRATION_FAILED",
        "evaluator_summaries": summaries, "failed_evaluators": failed,
        "maximum_mean_absolute_error": float(maximum_mean_absolute_error),
        "maximum_single_error": float(maximum_single_error),
        "reference_labels_independently_verified": False,
    })


def stage283_check_sample_adequacy(*, task_records: Sequence[Mapping],
                                   minimum_tasks_per_domain: int = 30,
                                   minimum_strata_per_domain: int = 2,
                                   held: bool = False):
    """Require unique task declarations and minimum domain/stratum coverage."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_records, Sequence) or isinstance(task_records, (str, bytes))
            or isinstance(minimum_tasks_per_domain, bool)
            or not isinstance(minimum_tasks_per_domain, int) or minimum_tasks_per_domain < 1
            or isinstance(minimum_strata_per_domain, bool)
            or not isinstance(minimum_strata_per_domain, int) or minimum_strata_per_domain < 1):
        return _blocked("task records and sample thresholds are invalid")
    ids, domains = set(), {}
    for row in task_records:
        if not isinstance(row, Mapping):
            return _blocked("each task record must be a mapping")
        task_id, domain, stratum, evidence = row.get("task_id"), row.get("domain"), row.get("stratum"), row.get("task_digest")
        if (not isinstance(task_id, str) or not task_id.strip() or task_id in ids
                or not isinstance(domain, str) or not domain.strip()
                or not isinstance(stratum, str) or not stratum.strip() or not _digest(evidence)):
            return _blocked("task identity, domain, stratum or digest is invalid")
        ids.add(task_id)
        domains.setdefault(domain, []).append(stratum)
    if not domains:
        return _blocked("at least one task domain is required")
    summaries, insufficient = [], []
    for domain, strata in sorted(domains.items()):
        count, strata_count = len(strata), len(set(strata))
        summaries.append({"domain": domain, "task_count": count, "stratum_count": strata_count})
        if count < minimum_tasks_per_domain or strata_count < minimum_strata_per_domain:
            insufficient.append(domain)
    return _seal({
        "status": "SAMPLE_ADEQUACY_PASSED" if not insufficient else "SAMPLE_ADEQUACY_FAILED",
        "domain_coverage": summaries, "insufficient_domains": insufficient,
        "task_set_digest": _hash(sorted(ids)),
        "task_representativeness_independently_verified": False,
    })


def stage284_compare_cross_model_reproducibility(*, model_a: Mapping, model_b: Mapping,
                                                  maximum_mean_absolute_gap: float = 0.10,
                                                  maximum_single_gap: float = 0.25,
                                                  minimum_paired_tasks: int = 3,
                                                  held: bool = False):
    """Compare two declared model score sets on identical task IDs and domains."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(model_a, Mapping) or not isinstance(model_b, Mapping):
        return _blocked("model score sets must be mappings")
    if (not isinstance(model_a.get("model_id"), str) or not model_a["model_id"].strip()
            or not isinstance(model_b.get("model_id"), str) or not model_b["model_id"].strip()
            or model_a["model_id"] == model_b["model_id"]
            or not _digest(model_a.get("task_set_digest"))
            or model_a.get("task_set_digest") != model_b.get("task_set_digest")
            or not isinstance(model_a.get("scores"), Sequence)
            or not isinstance(model_b.get("scores"), Sequence)
            or isinstance(model_a.get("scores"), (str, bytes))
            or isinstance(model_b.get("scores"), (str, bytes))
            or isinstance(minimum_paired_tasks, bool) or not isinstance(minimum_paired_tasks, int)
            or minimum_paired_tasks < 3
            or not _number(maximum_mean_absolute_gap) or not 0 <= maximum_mean_absolute_gap <= 1
            or not _number(maximum_single_gap) or not 0 <= maximum_single_gap <= 1):
        return _blocked("model identities, shared task digest, scores or thresholds are invalid")

    # Evidence digest is used as a declared task-row key; task_id must also be present and unique.
    def keyed(rows):
        result = {}
        for row in rows:
            if not isinstance(row, Mapping):
                return None
            domain, task_id, score, evidence = row.get("domain"), row.get("task_id"), row.get("score"), row.get("evidence_digest")
            if (not isinstance(domain, str) or not domain.strip()
                    or not isinstance(task_id, str) or not task_id.strip()
                    or not _number(score) or not 0 <= score <= 1 or not _digest(evidence)
                    or (domain, task_id) in result):
                return None
            result[(domain, task_id)] = (float(score), evidence)
        return result

    a, b = keyed(model_a["scores"]), keyed(model_b["scores"])
    if a is None or b is None or not a or set(a) != set(b):
        return _blocked("models must provide unique scores for the exact same non-empty domain/task pairs")
    task_ids = sorted({task_id for _, task_id in a})
    if len(task_ids) < minimum_paired_tasks:
        return _blocked("paired task count is below the minimum")
    if model_a["task_set_digest"] != _hash(task_ids):
        return _blocked("declared task-set digest does not match the paired task IDs")
    if any(a[key][1] != b[key][1] for key in a):
        return _blocked("paired model scores must bind identical per-task evidence digests")
    gaps = [abs(a[key][0] - b[key][0]) for key in sorted(a)]
    mean_gap, max_gap = sum(gaps) / len(gaps), max(gaps)
    matches = mean_gap <= maximum_mean_absolute_gap and max_gap <= maximum_single_gap
    return _seal({
        "status": "CROSS_MODEL_REPRODUCIBILITY_WITHIN_LIMIT" if matches else "CROSS_MODEL_REPRODUCIBILITY_FAILED",
        "model_a_id": model_a["model_id"], "model_b_id": model_b["model_id"],
        "paired_task_count": len(gaps), "mean_absolute_score_gap": mean_gap,
        "maximum_single_score_gap": max_gap,
        "maximum_mean_absolute_gap": float(maximum_mean_absolute_gap),
        "maximum_single_gap": float(maximum_single_gap),
        "model_independence_or_equivalence_proven": False,
    })


def stage285_integrate_capability_evaluation(*, protocol_result: Mapping,
                                            calibration_result: Mapping,
                                            sample_result: Mapping,
                                            cross_model_result: Mapping,
                                            held: bool = False):
    """Fail-closed evidence integration; passing is not execution or ASI authorization."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    checks = (
        (protocol_result, "PROTOCOL_UNCHANGED"),
        (calibration_result, "EVALUATORS_CALIBRATED"),
        (sample_result, "SAMPLE_ADEQUACY_PASSED"),
        (cross_model_result, "CROSS_MODEL_REPRODUCIBILITY_WITHIN_LIMIT"),
    )
    if not all(_valid(result, status) for result, status in checks):
        return _blocked("all four sealed protocol, calibration, sample and cross-model checks must pass")
    return _seal({
        "status": "CAPABILITY_EVALUATION_EVIDENCE_INTEGRATED",
        "protocol_digest": protocol_result["result_digest"],
        "calibration_digest": calibration_result["result_digest"],
        "sample_adequacy_digest": sample_result["result_digest"],
        "cross_model_digest": cross_model_result["result_digest"],
        "decision_scope": "evidence integration only",
        "general_capability_gain_proven": False,
        "rsi_or_asi_demonstrated": False,
        "next_step": "ELIGIBLE_FOR_SEPARATE_REVIEW",
    })
