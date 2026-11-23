"""Stages 306-310: stratified evidence balance, rubric parity and freshness.

All inputs are caller-supplied declarations. These checks are evidence-quality
screens only and never authorize task execution, experiments, model changes,
HOLD release, merge or deployment.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
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


def _num(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _sealed(value, expected_status):
    if not isinstance(value, Mapping) or value.get("status") != expected_status:
        return False
    if any(value.get(key) is not flag for key, flag in _FALSE.items()):
        return False
    try:
        return _digest(value.get("result_digest")) and value["result_digest"] == _hash(
            {key: item for key, item in value.items() if key != "result_digest"}
        )
    except (TypeError, ValueError, OverflowError):
        return False


def stage306_check_stratum_balance(*, baseline_counts: Mapping, candidate_counts: Mapping,
                                   minimum_per_stratum: int = 3,
                                   maximum_total_variation: float = 0.10, held: bool = False):
    """Require identical declared strata, minimum counts and bounded mix shift."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(baseline_counts, Mapping) or not isinstance(candidate_counts, Mapping)
            or not baseline_counts or set(baseline_counts) != set(candidate_counts)
            or isinstance(minimum_per_stratum, bool) or not isinstance(minimum_per_stratum, int)
            or minimum_per_stratum < 1 or not _num(maximum_total_variation)
            or not 0 <= maximum_total_variation <= 1):
        return _blocked("strata, minimum count or threshold is invalid")
    for counts in (baseline_counts, candidate_counts):
        if any(not isinstance(key, str) or not key.strip() or isinstance(value, bool)
               or not isinstance(value, int) or value < minimum_per_stratum
               for key, value in counts.items()):
            return _blocked("each declared stratum must meet the minimum count")
    btotal, ctotal = sum(baseline_counts.values()), sum(candidate_counts.values())
    if btotal <= 0 or ctotal <= 0:
        return _blocked("stratum totals must be positive")
    shares = {
        key: {"baseline_share": baseline_counts[key] / btotal,
              "candidate_share": candidate_counts[key] / ctotal}
        for key in sorted(baseline_counts)
    }
    tv = sum(abs(row["baseline_share"] - row["candidate_share"]) for row in shares.values()) / 2
    passed = tv <= maximum_total_variation
    return _seal({
        "status": "STRATUM_BALANCE_PASSED" if passed else "STRATUM_BALANCE_FAILED",
        "stratum_count": len(shares), "minimum_per_stratum": minimum_per_stratum,
        "total_variation_distance": tv, "maximum_total_variation": float(maximum_total_variation),
        "shares": shares, "sampling_frame_independently_verified": False,
    })


def stage307_check_scoring_rubric_parity(*, preregistered_version: str,
                                         observed_version: str,
                                         preregistered_digest: str,
                                         observed_digest: str, held: bool = False):
    """Require exact declared rubric version and content-digest parity."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(preregistered_version, str) or not preregistered_version.strip()
            or not isinstance(observed_version, str) or not observed_version.strip()
            or not _digest(preregistered_digest) or not _digest(observed_digest)):
        return _blocked("rubric versions or digests are invalid")
    passed = preregistered_version == observed_version and preregistered_digest == observed_digest
    return _seal({
        "status": "SCORING_RUBRIC_PARITY_PASSED" if passed else "SCORING_RUBRIC_DRIFT",
        "rubric_version": observed_version, "rubric_digest": observed_digest,
        "exact_declared_parity": passed, "rubric_source_authenticated": False,
    })


def _aware_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def stage308_check_evidence_freshness(*, evidence_created_at: str, evaluated_at: str,
                                      maximum_age_seconds: int = 86400, held: bool = False):
    """Reject stale, future-dated, naive or malformed evidence timestamps."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    created, evaluated = _aware_datetime(evidence_created_at), _aware_datetime(evaluated_at)
    if (created is None or evaluated is None or isinstance(maximum_age_seconds, bool)
            or not isinstance(maximum_age_seconds, int) or maximum_age_seconds < 0):
        return _blocked("timestamps must be timezone-aware ISO-8601 and age limit nonnegative")
    age = (evaluated - created).total_seconds()
    if age < 0:
        return _blocked("evidence timestamp is later than evaluation timestamp")
    passed = age <= maximum_age_seconds
    return _seal({
        "status": "EVIDENCE_FRESH" if passed else "EVIDENCE_STALE",
        "evidence_age_seconds": age, "maximum_age_seconds": maximum_age_seconds,
        "timestamp_source_trusted": False,
    })


def stage309_check_domain_missingness(*, domain_counts: Mapping,
                                      maximum_missing_fraction: float = 0.10,
                                      minimum_total_per_domain: int = 3, held: bool = False):
    """Check missingness rates independently for every declared domain."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(domain_counts, Mapping) or not domain_counts
            or not _num(maximum_missing_fraction) or not 0 <= maximum_missing_fraction < 1
            or isinstance(minimum_total_per_domain, bool)
            or not isinstance(minimum_total_per_domain, int) or minimum_total_per_domain < 1):
        return _blocked("domain counts or thresholds are invalid")
    rows = {}
    for domain, counts in domain_counts.items():
        if (not isinstance(domain, str) or not domain.strip() or not isinstance(counts, Mapping)
                or set(counts) != {"observed", "missing"}):
            return _blocked("each domain requires observed and missing integer counts")
        observed, missing = counts["observed"], counts["missing"]
        if (isinstance(observed, bool) or not isinstance(observed, int) or observed < 0
                or isinstance(missing, bool) or not isinstance(missing, int) or missing < 0
                or observed + missing < minimum_total_per_domain):
            return _blocked("domain counts must be nonnegative and meet the minimum total")
        fraction = missing / (observed + missing)
        rows[domain] = {"observed": observed, "missing": missing, "missing_fraction": fraction}
    passed = all(row["missing_fraction"] <= maximum_missing_fraction for row in rows.values())
    return _seal({
        "status": "DOMAIN_MISSINGNESS_PASSED" if passed else "DOMAIN_MISSINGNESS_FAILED",
        "maximum_missing_fraction": float(maximum_missing_fraction),
        "minimum_total_per_domain": minimum_total_per_domain,
        "domains": {key: rows[key] for key in sorted(rows)},
        "missingness_mechanism_verified": False,
    })


def stage310_integrate_stratified_evidence_quality(*, stratum_result: Mapping,
                                                    rubric_result: Mapping,
                                                    freshness_result: Mapping,
                                                    missingness_result: Mapping,
                                                    held: bool = False):
    """Fail closed unless every new quality gate is sealed and passing."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates = (
        (stratum_result, "STRATUM_BALANCE_PASSED"),
        (rubric_result, "SCORING_RUBRIC_PARITY_PASSED"),
        (freshness_result, "EVIDENCE_FRESH"),
        (missingness_result, "DOMAIN_MISSINGNESS_PASSED"),
    )
    if not all(_sealed(result, status) for result, status in gates):
        return _blocked("all four sealed stratified evidence-quality gates must pass")
    return _seal({
        "status": "STRATIFIED_EVIDENCE_QUALITY_PASSED",
        "evidence_digests": [result["result_digest"] for result, _ in gates],
        "decision_scope": "proposal eligibility for separate independent review only",
        "sampling_integrity_proven": False, "rubric_authenticity_proven": False,
        "evidence_timestamp_trusted": False, "capability_gain_proven": False,
        "recursive_self_improvement_proven": False, "asi_demonstrated": False,
    })
