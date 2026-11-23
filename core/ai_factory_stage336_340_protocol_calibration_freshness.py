"""Stages 336-340: protocol commitment, evaluator agreement, calibration and freshness."""
from __future__ import annotations
from collections.abc import Mapping
from hashlib import sha256
import json
import math

_FALSE = {"proposal_only": True, "task_execution_authorized": False,
          "experiment_execution_authorized": False, "model_change_authorized": False,
          "merge_deploy_authorized": False, "hold_release_authorized": False}


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _digest(result)
    return result


def _valid(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    try:
        d = result.get("result_digest")
        return isinstance(d, str) and len(d) == 64 and d == _digest({k:v for k,v in result.items() if k != "result_digest"})
    except (TypeError, ValueError, OverflowError):
        return False


def _finite(v):
    return not isinstance(v, bool) and isinstance(v, (int,float)) and math.isfinite(v)


def stage336_check_protocol_commitment(*, declared_protocol: Mapping, observed_protocol: Mapping,
                                       required_fields: list, held: bool = False):
    """Require exact protocol equality and complete predeclared fields; hashes are not signatures."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(declared_protocol, Mapping) or not isinstance(observed_protocol, Mapping)
            or not isinstance(required_fields, list) or not required_fields
            or any(not isinstance(x,str) or not x for x in required_fields)
            or len(set(required_fields)) != len(required_fields)):
        return _blocked("protocol commitment inputs are malformed")
    if any(k not in declared_protocol or k not in observed_protocol for k in required_fields):
        return _blocked("required protocol field is missing")
    declared = {k: declared_protocol[k] for k in required_fields}
    observed = {k: observed_protocol[k] for k in required_fields}
    try:
        same = _digest(declared) == _digest(observed)
    except (TypeError, ValueError, OverflowError):
        return _blocked("protocol contains non-canonical values")
    return _seal({"status":"PROTOCOL_COMMITMENT_MATCHED" if same else "PROTOCOL_COMMITMENT_MISMATCH",
                  "declared_digest":_digest(declared), "observed_digest":_digest(observed),
                  "required_fields":sorted(required_fields), "commitment_authenticated":False})


def stage337_check_evaluator_agreement(*, task_evaluator_scores: Mapping,
                                       maximum_task_score_range: float = 0.25,
                                       minimum_tasks: int = 3, held: bool = False):
    """Bound per-task evaluator disagreement across a common declared task set."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_evaluator_scores, Mapping) or not task_evaluator_scores
            or not _finite(maximum_task_score_range) or maximum_task_score_range < 0
            or isinstance(minimum_tasks,bool) or not isinstance(minimum_tasks,int) or minimum_tasks < 1
            or len(task_evaluator_scores) < minimum_tasks):
        return _blocked("evaluator agreement inputs are invalid")
    ranges={}
    for task, scores in task_evaluator_scores.items():
        if not isinstance(task,str) or not task or not isinstance(scores,Mapping) or len(scores)<2:
            return _blocked("each task needs at least two evaluator scores")
        if any(not isinstance(k,str) or not k or not _finite(v) for k,v in scores.items()):
            return _blocked("evaluator scores must be finite and identified")
        ranges[task]=max(scores.values())-min(scores.values())
    worst=max(ranges.values())
    return _seal({"status":"EVALUATOR_AGREEMENT_PASSED" if worst <= maximum_task_score_range else "EVALUATOR_AGREEMENT_FAILED",
                  "task_score_ranges":dict(sorted(ranges.items())), "maximum_observed_range":worst,
                  "maximum_task_score_range":float(maximum_task_score_range),
                  "evaluator_independence_proven":False})


def stage338_check_calibration_bins(*, bins: list, maximum_calibration_error: float = 0.1,
                                    minimum_bin_count: int = 5, held: bool = False):
    """Check declared confidence/accuracy bins using count-weighted absolute calibration error."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(bins,list) or not bins or not _finite(maximum_calibration_error)
            or not 0 <= maximum_calibration_error <= 1
            or isinstance(minimum_bin_count,bool) or not isinstance(minimum_bin_count,int) or minimum_bin_count < 1):
        return _blocked("calibration inputs or bounds are invalid")
    total=0
    weighted=0.0
    for row in bins:
        if (not isinstance(row,Mapping) or set(row)!={"count","mean_confidence","observed_accuracy"}
                or isinstance(row["count"],bool) or not isinstance(row["count"],int)
                or row["count"] < minimum_bin_count
                or not _finite(row["mean_confidence"]) or not 0 <= row["mean_confidence"] <= 1
                or not _finite(row["observed_accuracy"]) or not 0 <= row["observed_accuracy"] <= 1):
            return _blocked("each calibration bin must meet count and bounded-value requirements")
        total += row["count"]
        weighted += row["count"]*abs(row["mean_confidence"]-row["observed_accuracy"])
    error=weighted/total
    return _seal({"status":"CALIBRATION_BINS_PASSED" if error <= maximum_calibration_error else "CALIBRATION_BINS_FAILED",
                  "weighted_calibration_error":error,"sample_count":total,
                  "maximum_calibration_error":float(maximum_calibration_error),
                  "calibration_sample_provenance_authenticated":False})


def stage339_check_evidence_freshness(*, evidence_timestamps: Mapping, reference_timestamp: int,
                                      maximum_age_seconds: int, held: bool = False):
    """Require every caller-supplied evidence timestamp to be recent and non-future."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evidence_timestamps,Mapping) or not evidence_timestamps
            or isinstance(reference_timestamp,bool) or not isinstance(reference_timestamp,int)
            or isinstance(maximum_age_seconds,bool) or not isinstance(maximum_age_seconds,int)
            or maximum_age_seconds < 0):
        return _blocked("freshness inputs are invalid")
    ages={}
    for name, stamp in evidence_timestamps.items():
        if not isinstance(name,str) or not name or isinstance(stamp,bool) or not isinstance(stamp,int):
            return _blocked("evidence names and timestamps must be integers")
        age=reference_timestamp-stamp
        if age < 0:
            return _blocked("future-dated evidence is not accepted")
        ages[name]=age
    worst=max(ages.values())
    return _seal({"status":"EVIDENCE_FRESHNESS_PASSED" if worst <= maximum_age_seconds else "EVIDENCE_FRESHNESS_FAILED",
                  "evidence_ages_seconds":dict(sorted(ages.items())),"maximum_observed_age_seconds":worst,
                  "maximum_age_seconds":maximum_age_seconds,"trusted_timestamp_proven":False})


def stage340_integrate_protocol_calibration(*, protocol_result: Mapping, agreement_result: Mapping,
                                            calibration_result: Mapping, freshness_result: Mapping,
                                            held: bool = False):
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates=((protocol_result,"PROTOCOL_COMMITMENT_MATCHED"),(agreement_result,"EVALUATOR_AGREEMENT_PASSED"),
           (calibration_result,"CALIBRATION_BINS_PASSED"),(freshness_result,"EVIDENCE_FRESHNESS_PASSED"))
    if not all(_valid(r,s) for r,s in gates):
        return _blocked("all four sealed protocol/calibration/freshness gates must pass")
    return _seal({"status":"PROTOCOL_CALIBRATION_FRESHNESS_PASSED",
                  "evidence_digests":[r["result_digest"] for r,_ in gates],
                  "decision_scope":"proposal eligibility for separate review only",
                  "protocol_authenticity_proven":False,"evaluator_independence_proven":False,
                  "calibration_validity_proven":False,"trusted_timestamps_proven":False,
                  "asi_demonstrated":False})
