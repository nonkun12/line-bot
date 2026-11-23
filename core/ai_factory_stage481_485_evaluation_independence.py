"""Evaluation-independence and leakage checks for AI Factory stages 481-485."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_split_disjointness(splits: Mapping[str, Sequence[str]], *,
                             required_splits: Sequence[str]) -> dict[str, Any]:
    """481: reject missing split declarations, duplicate IDs, and cross-split overlap."""
    errors: list[str] = []
    required = list(required_splits)
    if len(required) < 2 or any(not _text(name) for name in required) or len(set(required)) != len(required):
        errors.append("required_split_declaration_invalid")
    observed: dict[str, set[str]] = {}
    owner: dict[str, str] = {}
    for name in required:
        values = splits.get(name)
        if values is None:
            errors.append(f"split_missing:{name}")
            continue
        current: set[str] = set()
        for i, value in enumerate(values):
            if not _text(value):
                errors.append(f"split_sample_id_invalid:{name}:{i}")
                continue
            if value in current:
                errors.append(f"split_duplicate_sample:{name}:{value}")
            current.add(value)
            if value in owner and owner[value] != name:
                errors.append(f"cross_split_leakage:{value}:{owner[value]}:{name}")
            else:
                owner[value] = name
        observed[name] = current
        if not current:
            errors.append(f"split_empty:{name}")
    return {"stage": 481, "pass": not errors, "errors": errors,
            "split_counts": {name: len(values) for name, values in observed.items()},
            "unique_sample_count": len(owner)}


def check_dataset_lineage(records: Sequence[Mapping[str, Any]], *,
                          required_fields: Sequence[str]) -> dict[str, Any]:
    """482: require unique dataset versions and explicit lineage references."""
    errors: list[str] = []
    seen: set[str] = set()
    if not required_fields or any(not _text(field) for field in required_fields):
        errors.append("lineage_required_fields_invalid")
    for i, record in enumerate(records):
        dataset_id, version = record.get("dataset_id"), record.get("version")
        key = f"{dataset_id}@{version}"
        if not _text(dataset_id) or not _text(version):
            errors.append(f"lineage_identity_invalid:{i}")
        elif key in seen:
            errors.append(f"lineage_duplicate_version:{key}")
        else:
            seen.add(key)
        for field in required_fields:
            if not _text(record.get(field)):
                errors.append(f"lineage_reference_missing:{i}:{field}")
    if not records:
        errors.append("lineage_records_empty")
    return {"stage": 482, "pass": not errors, "errors": errors,
            "dataset_version_count": len(seen)}


def check_calibration_evidence(calibration: Mapping[str, Any], *,
                               minimum_samples: int, maximum_error: float) -> dict[str, Any]:
    """483: validate declared calibration sample count and finite bounded error."""
    errors: list[str] = []
    count, error = calibration.get("sample_count"), calibration.get("error")
    if not isinstance(minimum_samples, int) or isinstance(minimum_samples, bool) or minimum_samples < 1:
        errors.append("calibration_minimum_samples_invalid")
        minimum = 1
    else:
        minimum = minimum_samples
    if not isinstance(count, int) or isinstance(count, bool) or count < minimum:
        errors.append("calibration_sample_count_insufficient")
    if not _finite(maximum_error) or maximum_error < 0:
        errors.append("calibration_maximum_error_invalid")
        limit = 0.0
    else:
        limit = float(maximum_error)
    if not _finite(error) or error < 0:
        errors.append("calibration_error_invalid")
    elif error > limit + 1e-12:
        errors.append("calibration_error_exceeded")
    for field in ("method_id", "dataset_ref", "evaluator_ref"):
        if not _text(calibration.get(field)):
            errors.append(f"calibration_{field}_missing")
    return {"stage": 483, "pass": not errors, "errors": errors,
            "sample_count": count if isinstance(count, int) else None,
            "observed_error": error if _finite(error) else None, "maximum_error": limit}


def check_external_reference(reference: Mapping[str, Any], *,
                             expected_protocol_id: str,
                             expected_metric_id: str) -> dict[str, Any]:
    """484: require an explicit, compatible external-reference declaration."""
    errors: list[str] = []
    for field in ("reference_id", "source_id", "version", "retrieval_ref"):
        if not _text(reference.get(field)):
            errors.append(f"external_reference_{field}_missing")
    if not _text(expected_protocol_id) or reference.get("protocol_id") != expected_protocol_id:
        errors.append("external_reference_protocol_mismatch")
    if not _text(expected_metric_id) or reference.get("metric_id") != expected_metric_id:
        errors.append("external_reference_metric_mismatch")
    if not _finite(reference.get("score")):
        errors.append("external_reference_score_invalid")
    return {"stage": 484, "pass": not errors, "errors": errors,
            "external_reference_declared": True}


def evaluate_stages_481_485(*, splits: Mapping[str, Sequence[str]],
                            required_splits: Sequence[str],
                            lineage_records: Sequence[Mapping[str, Any]],
                            required_lineage_fields: Sequence[str],
                            calibration: Mapping[str, Any], minimum_calibration_samples: int,
                            maximum_calibration_error: float,
                            external_reference: Mapping[str, Any],
                            expected_protocol_id: str, expected_metric_id: str,
                            unresolved_holds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """485: aggregate independent-evaluation declarations and fail closed."""
    checks = [
        check_split_disjointness(splits, required_splits=required_splits),
        check_dataset_lineage(lineage_records, required_fields=required_lineage_fields),
        check_calibration_evidence(calibration, minimum_samples=minimum_calibration_samples,
                                   maximum_error=maximum_calibration_error),
        check_external_reference(external_reference, expected_protocol_id=expected_protocol_id,
                                 expected_metric_id=expected_metric_id),
    ]
    hold_errors: list[str] = []
    for i, hold in enumerate(unresolved_holds):
        if not _text(hold.get("hold_id")) or not _text(hold.get("reason")):
            hold_errors.append(f"hold_declaration_invalid:{i}")
    if unresolved_holds:
        hold_errors.append("unresolved_holds_present")
    checks.append({"stage": 485, "pass": not hold_errors, "errors": hold_errors})
    passed = all(check["pass"] for check in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 485, "status": "READY_FOR_REVIEW" if passed else "HOLD",
            "checks": checks, "seal": _seal(record),
            "data_independence_verified": False, "external_validity_verified": False,
            "evidence_authenticity_verified": False, "execution_authorized": False,
            "promotion_authorized": False, "proposal_only": True}
