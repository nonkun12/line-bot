"""Proposal-only evidence quality and readiness gates for AI Factory stages 371-375."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check_evidence_freshness(records: Sequence[Mapping[str, Any]], *,
                             now_epoch: int, maximum_age_seconds: int) -> dict[str, Any]:
    """Stage 371: reject missing, future-dated, or stale evidence timestamps."""
    errors = []
    ages = []
    if not records:
        errors.append("evidence_empty")
    if isinstance(now_epoch, bool) or not isinstance(now_epoch, int) or now_epoch < 0:
        errors.append("now_epoch_invalid")
    if (isinstance(maximum_age_seconds, bool) or
            not isinstance(maximum_age_seconds, int) or maximum_age_seconds < 0):
        errors.append("maximum_age_invalid")
    for index, record in enumerate(records):
        stamp = record.get("timestamp")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
            errors.append(f"timestamp_invalid:{index}")
            continue
        age = now_epoch - stamp
        if age < 0:
            errors.append(f"timestamp_in_future:{index}")
        elif isinstance(maximum_age_seconds, int) and not isinstance(maximum_age_seconds, bool) and age > maximum_age_seconds:
            errors.append(f"evidence_stale:{index}")
        ages.append(age)
    return {"stage": 371, "pass": not errors, "errors": errors, "ages_seconds": ages}


def check_metric_schema_compatibility(schemas: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 372: require each run to declare the same nonempty metric schema digest."""
    errors = []
    digests = [str(item.get("schema_digest", "")).strip() for item in schemas]
    if not schemas:
        errors.append("schemas_empty")
    if any(not value for value in digests):
        errors.append("schema_digest_missing")
    if len(set(digests)) > 1:
        errors.append("schema_digest_mismatch")
    return {"stage": 372, "pass": not errors, "errors": errors,
            "schema_digest": digests[0] if digests and len(set(digests)) == 1 and digests[0] else None}


def check_missingness_rate(total_fields: int, missing_fields: int,
                            maximum_missing_rate: float) -> dict[str, Any]:
    """Stage 373: bound declared missingness; malformed counts fail closed."""
    errors = []
    if isinstance(total_fields, bool) or not isinstance(total_fields, int) or total_fields <= 0:
        errors.append("total_fields_invalid")
    if isinstance(missing_fields, bool) or not isinstance(missing_fields, int) or missing_fields < 0:
        errors.append("missing_fields_invalid")
    if (isinstance(maximum_missing_rate, bool) or
            not isinstance(maximum_missing_rate, (int, float)) or
            not 0 <= maximum_missing_rate <= 1):
        errors.append("maximum_missing_rate_invalid")
    rate = missing_fields / total_fields if not errors else None
    if rate is not None and missing_fields > total_fields:
        errors.append("missing_exceeds_total")
    if rate is not None and not errors and rate > maximum_missing_rate:
        errors.append("missingness_rate_exceeded")
    return {"stage": 373, "pass": not errors, "errors": errors, "missing_rate": rate}


def check_evidence_category_coverage(required: Sequence[str],
                                     supplied: Sequence[str]) -> dict[str, Any]:
    """Stage 374: require exact coverage of required evidence categories."""
    errors = []
    required_set, supplied_set = set(required), set(supplied)
    if not required_set:
        errors.append("required_categories_empty")
    if len(required_set) != len(required):
        errors.append("required_category_duplicate")
    if len(supplied_set) != len(supplied):
        errors.append("supplied_category_duplicate")
    missing = sorted(required_set - supplied_set)
    unexpected = sorted(supplied_set - required_set)
    if missing:
        errors.append("required_category_missing")
    if unexpected:
        errors.append("unexpected_category")
    return {"stage": 374, "pass": not errors, "errors": errors,
            "missing": missing, "unexpected": unexpected}


def evaluate_stages_371_375(*, evidence: Sequence[Mapping[str, Any]],
                            now_epoch: int, maximum_age_seconds: int,
                            metric_schemas: Sequence[Mapping[str, Any]],
                            total_fields: int, missing_fields: int,
                            maximum_missing_rate: float,
                            required_categories: Sequence[str],
                            supplied_categories: Sequence[str]) -> dict[str, Any]:
    """Stage 375: aggregate evidence-quality gates; never grants execution."""
    checks = [
        check_evidence_freshness(evidence, now_epoch=now_epoch,
                                 maximum_age_seconds=maximum_age_seconds),
        check_metric_schema_compatibility(metric_schemas),
        check_missingness_rate(total_fields, missing_fields, maximum_missing_rate),
        check_evidence_category_coverage(required_categories, supplied_categories),
    ]
    payload = {"checks": checks, "all_pass": all(item["pass"] for item in checks),
               "execution_authorized": False, "proposal_only": True}
    return {"stage": 375, "status": "PASS" if payload["all_pass"] else "BLOCKED",
            "checks": checks, "seal": _seal(payload),
            "execution_authorized": False, "proposal_only": True}
