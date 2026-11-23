"""Stages 296-300: evidence quality and capability-evidence gates.

Caller-supplied evidence only. Hashes are integrity links, not authentication.
No stage authorizes execution, training, model changes, merge/deploy or HOLD release.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math

_FALSE = {"proposal_only": True, "task_execution_authorized": False,
          "experiment_execution_authorized": False, "model_change_authorized": False,
          "merge_deploy_authorized": False, "hold_release_authorized": False}


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


def _sealed(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    try:
        return _digest(result.get("result_digest")) and result["result_digest"] == _hash(
            {k: v for k, v in result.items() if k != "result_digest"})
    except (TypeError, ValueError):
        return False


def stage296_check_evidence_completeness(*, evidence_records: Sequence[Mapping],
                                         required_fields: Sequence[str],
                                         minimum_records: int = 3,
                                         held: bool = False):
    """Require complete, unique, digest-bound records without asserting authenticity."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evidence_records, Sequence) or isinstance(evidence_records, (str, bytes))
            or not isinstance(required_fields, Sequence) or isinstance(required_fields, (str, bytes))
            or isinstance(minimum_records, bool) or not isinstance(minimum_records, int)
            or minimum_records < 1):
        return _blocked("records, required fields or minimum count are invalid")
    fields = list(required_fields)
    if (not fields or any(not isinstance(x, str) or not x.strip() for x in fields)
            or len(set(fields)) != len(fields)):
        return _blocked("required fields must be nonempty unique strings")
    seen, missing = set(), []
    for record in evidence_records:
        if not isinstance(record, Mapping):
            return _blocked("each evidence record must be a mapping")
        rid, digest = record.get("record_id"), record.get("evidence_digest")
        if not isinstance(rid, str) or not rid.strip() or rid in seen or not _digest(digest):
            return _blocked("record ID or evidence digest is invalid or duplicated")
        seen.add(rid)
        absent = [field for field in fields if field not in record or record[field] is None]
        if absent:
            missing.append({"record_id": rid, "missing_fields": absent})
    if len(seen) < minimum_records:
        return _blocked("minimum evidence record count not met")
    complete = not missing
    return _seal({"status": "EVIDENCE_COMPLETE" if complete else "EVIDENCE_INCOMPLETE",
                  "record_count": len(seen), "required_fields": fields,
                  "incomplete_records": missing, "record_ids_digest": _hash(sorted(seen)),
                  "external_authenticity_verified": False})


def stage297_check_uncertainty_quality(*, domain_intervals: Sequence[Mapping],
                                       maximum_interval_width: float = 0.20,
                                       held: bool = False):
    """Require bounded finite intervals and cap their width per domain."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(domain_intervals, Sequence) or isinstance(domain_intervals, (str, bytes))
            or not _num(maximum_interval_width) or not 0 <= maximum_interval_width <= 1):
        return _blocked("intervals or width threshold are invalid")
    seen, summary, wide = set(), [], []
    for row in domain_intervals:
        if not isinstance(row, Mapping):
            return _blocked("each interval must be a mapping")
        domain, lower, upper, evidence = (row.get("domain"), row.get("lower"),
                                           row.get("upper"), row.get("evidence_digest"))
        if (not isinstance(domain, str) or not domain.strip() or domain in seen
                or not _num(lower) or not _num(upper) or not 0 <= lower <= upper <= 1
                or not _digest(evidence)):
            return _blocked("domain, interval bounds or digest is invalid")
        seen.add(domain)
        width = float(upper - lower)
        summary.append({"domain": domain, "lower": float(lower), "upper": float(upper),
                        "width": width})
        if width > maximum_interval_width:
            wide.append(domain)
    if not seen:
        return _blocked("at least one domain interval is required")
    return _seal({"status": "UNCERTAINTY_WITHIN_LIMIT" if not wide else "UNCERTAINTY_TOO_WIDE",
                  "domain_intervals": sorted(summary, key=lambda x: x["domain"]),
                  "wide_interval_domains": sorted(wide),
                  "interval_method_and_coverage_independently_verified": False})


def stage298_check_task_family_coverage(*, task_family_counts: Sequence[Mapping],
                                        required_families: Sequence[str],
                                        minimum_per_family: int = 5,
                                        held: bool = False):
    """Require declared task-family coverage and reject unrequested/missing strata."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_family_counts, Sequence) or isinstance(task_family_counts, (str, bytes))
            or not isinstance(required_families, Sequence) or isinstance(required_families, (str, bytes))
            or isinstance(minimum_per_family, bool) or not isinstance(minimum_per_family, int)
            or minimum_per_family < 1):
        return _blocked("family counts, required families or minimum are invalid")
    required = list(required_families)
    if (not required or any(not isinstance(x, str) or not x.strip() for x in required)
            or len(set(required)) != len(required)):
        return _blocked("required family names must be unique nonempty strings")
    counts = {}
    for row in task_family_counts:
        if not isinstance(row, Mapping):
            return _blocked("each family count must be a mapping")
        family, count, digest = row.get("family"), row.get("count"), row.get("manifest_digest")
        if (not isinstance(family, str) or not family.strip() or family in counts
                or isinstance(count, bool) or not isinstance(count, int) or count < 0
                or not _digest(digest)):
            return _blocked("family, count or manifest digest is invalid or duplicated")
        counts[family] = count
    if set(counts) != set(required):
        return _blocked("provided task families must exactly match required families")
    deficient = sorted(name for name, count in counts.items() if count < minimum_per_family)
    return _seal({"status": "TASK_FAMILY_COVERAGE_PASSED" if not deficient else "TASK_FAMILY_COVERAGE_GAP",
                  "family_counts": dict(sorted(counts.items())), "deficient_families": deficient,
                  "family_manifest_digest": _hash(counts)})


def stage299_check_cross_run_consistency(*, run_summaries: Sequence[Mapping],
                                         maximum_score_difference: float = 0.05,
                                         minimum_runs: int = 3, held: bool = False):
    """Check repeated run summaries for stable per-domain reported scores."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(run_summaries, Sequence) or isinstance(run_summaries, (str, bytes))
            or isinstance(minimum_runs, bool) or not isinstance(minimum_runs, int)
            or minimum_runs < 3 or not _num(maximum_score_difference)
            or not 0 <= maximum_score_difference <= 1):
        return _blocked("run summaries or consistency thresholds are invalid")
    run_ids, domains_by_run, grouped = set(), [], {}
    for run in run_summaries:
        if not isinstance(run, Mapping):
            return _blocked("each run summary must be a mapping")
        run_id, scores, digest = run.get("run_id"), run.get("domain_scores"), run.get("evidence_digest")
        if not isinstance(run_id, str) or not run_id.strip() or run_id in run_ids or not isinstance(scores, Mapping) or not _digest(digest):
            return _blocked("run identity, scores or evidence digest is invalid")
        run_ids.add(run_id)
        if not scores:
            return _blocked("each run must contain domain scores")
        current = set(scores)
        if any(not isinstance(d, str) or not d.strip() or not _num(v) or not 0 <= v <= 1
               for d, v in scores.items()):
            return _blocked("domain score names or values are invalid")
        domains_by_run.append(current)
        for domain, score in scores.items():
            grouped.setdefault(domain, []).append(float(score))
    if len(run_ids) < minimum_runs:
        return _blocked("minimum distinct run count not met")
    if any(domains != domains_by_run[0] for domains in domains_by_run[1:]):
        return _blocked("all runs must report the same domain set")
    summary, inconsistent = [], []
    for domain, values in sorted(grouped.items()):
        spread = max(values) - min(values)
        summary.append({"domain": domain, "run_count": len(values), "score_range": spread})
        if spread > maximum_score_difference:
            inconsistent.append(domain)
    return _seal({"status": "CROSS_RUN_CONSISTENT" if not inconsistent else "CROSS_RUN_VARIANCE_DETECTED",
                  "domain_consistency": summary, "inconsistent_domains": inconsistent,
                  "run_independence_and_environment_parity_verified": False})


def stage300_integrate_capability_evidence(*, completeness_result: Mapping,
                                           uncertainty_result: Mapping,
                                           coverage_result: Mapping,
                                           consistency_result: Mapping,
                                           held: bool = False):
    """Integrate evidence-quality gates into proposal-only research eligibility."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    required = ((completeness_result, "EVIDENCE_COMPLETE"),
                (uncertainty_result, "UNCERTAINTY_WITHIN_LIMIT"),
                (coverage_result, "TASK_FAMILY_COVERAGE_PASSED"),
                (consistency_result, "CROSS_RUN_CONSISTENT"))
    if not all(_sealed(item, status) for item, status in required):
        return _blocked("all four sealed capability-evidence gates must pass")
    return _seal({"status": "CAPABILITY_EVIDENCE_QUALITY_PASSED",
                  "evidence_digests": [item["result_digest"] for item, _ in required],
                  "decision_scope": "eligibility for separate independent review only",
                  "capability_gain_proven": False, "recursive_self_improvement_proven": False,
                  "asi_demonstrated": False, "next_step": "ELIGIBLE_FOR_SEPARATE_RESEARCH_REVIEW"})
