"""Proposal-only controls for AI Factory stages 366-370.

All inputs are caller-supplied declarations. These checks validate consistency and
completeness, not truth, provenance, evaluator independence, or execution safety.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def check_cross_run_consistency(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 366: require unique run IDs and a shared declared protocol digest."""
    ids = [str(run.get("run_id", "")).strip() for run in runs]
    protocols = [str(run.get("protocol_digest", "")).strip() for run in runs]
    errors = []
    if not runs:
        errors.append("runs_empty")
    if any(not item for item in ids):
        errors.append("run_id_missing")
    if len(set(ids)) != len(ids):
        errors.append("run_id_duplicate")
    if any(not item for item in protocols):
        errors.append("protocol_digest_missing")
    if len(set(protocols)) > 1:
        errors.append("protocol_digest_mismatch")
    return {"stage": 366, "pass": not errors, "errors": errors,
            "run_count": len(runs), "protocol_digest": protocols[0] if protocols and len(set(protocols)) == 1 else None}


def check_independent_validation_declarations(validators: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 367: reject shared declared identities/lineage; cannot prove independence."""
    errors = []
    identities = [str(v.get("validator_id", "")).strip() for v in validators]
    lineages = [str(v.get("lineage_id", "")).strip() for v in validators]
    if len(validators) < 2:
        errors.append("at_least_two_validators_required")
    if any(not value for value in identities):
        errors.append("validator_id_missing")
    if any(not value for value in lineages):
        errors.append("lineage_id_missing")
    if len(set(identities)) != len(identities):
        errors.append("validator_identity_collision")
    if len(set(lineages)) != len(lineages):
        errors.append("validator_lineage_collision")
    return {"stage": 367, "pass": not errors, "errors": errors,
            "validator_count": len(validators), "independence_proven": False}


def check_anomaly_rate(observed: int, population: int, maximum_rate: float) -> dict[str, Any]:
    """Stage 368: bound a declared anomaly rate; invalid denominators fail closed."""
    errors = []
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
        errors.append("observed_invalid")
    if isinstance(population, bool) or not isinstance(population, int) or population <= 0:
        errors.append("population_invalid")
    if not isinstance(maximum_rate, (int, float)) or isinstance(maximum_rate, bool) or not 0 <= maximum_rate <= 1:
        errors.append("maximum_rate_invalid")
    rate = observed / population if not errors else None
    if rate is not None and observed > population:
        errors.append("observed_exceeds_population")
    if rate is not None and not errors and rate > maximum_rate:
        errors.append("anomaly_rate_exceeded")
    return {"stage": 368, "pass": not errors, "errors": errors, "observed_rate": rate,
            "maximum_rate": maximum_rate}


def check_cohort_coverage(expected: Sequence[str], observed: Sequence[str]) -> dict[str, Any]:
    """Stage 369: require exact, nonempty cohort coverage without duplicates."""
    expected_set, observed_set = set(expected), set(observed)
    errors = []
    if not expected_set:
        errors.append("expected_cohorts_empty")
    if len(expected_set) != len(expected):
        errors.append("expected_cohort_duplicate")
    if len(observed_set) != len(observed):
        errors.append("observed_cohort_duplicate")
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    if missing:
        errors.append("cohort_missing")
    if unexpected:
        errors.append("unexpected_cohort")
    return {"stage": 369, "pass": not errors, "errors": errors,
            "missing": missing, "unexpected": unexpected}


def evaluate_stages_366_370(*, runs: Sequence[Mapping[str, Any]],
                            validators: Sequence[Mapping[str, Any]],
                            observed_anomalies: int, population: int,
                            maximum_anomaly_rate: float,
                            expected_cohorts: Sequence[str],
                            observed_cohorts: Sequence[str]) -> dict[str, Any]:
    """Stage 370: sealed deterministic summary; any failed subgate blocks."""
    checks = [
        check_cross_run_consistency(runs),
        check_independent_validation_declarations(validators),
        check_anomaly_rate(observed_anomalies, population, maximum_anomaly_rate),
        check_cohort_coverage(expected_cohorts, observed_cohorts),
    ]
    payload = {"stages": checks, "all_pass": all(item["pass"] for item in checks),
               "execution_authorized": False, "proposal_only": True}
    return {"stage": 370, "status": "PASS" if payload["all_pass"] else "BLOCKED",
            "checks": checks, "execution_authorized": False, "proposal_only": True,
            "seal": _digest(payload)}
