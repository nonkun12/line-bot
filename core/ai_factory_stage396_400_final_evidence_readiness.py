"""Proposal-only final evidence readiness gates for AI Factory stages 396-400."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _seal(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check_source_provenance_declarations(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 396: require unique evidence IDs and non-empty source/version declarations."""
    errors: list[str] = []
    seen: set[str] = set()
    if not records:
        errors.append("provenance_records_empty")
    for i, item in enumerate(records):
        evidence_id, source, version = item.get("evidence_id"), item.get("source_ref"), item.get("source_version")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            errors.append(f"evidence_id_invalid:{i}")
        elif evidence_id in seen:
            errors.append(f"evidence_id_duplicate:{evidence_id}")
        else:
            seen.add(evidence_id)
        for field, value in (("source_ref", source), ("source_version", version)):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field}_missing:{i}")
    return {"stage": 396, "pass": not errors, "errors": errors,
            "declared_evidence_count": len(seen)}


def check_evidence_time_windows(records: Sequence[Mapping[str, Any]], *,
                                maximum_age_seconds: int,
                                evaluation_time: int) -> dict[str, Any]:
    """Stage 397: validate integer timestamps, ordering, future dates, and maximum age."""
    errors: list[str] = []
    if isinstance(maximum_age_seconds, bool) or not isinstance(maximum_age_seconds, int) or maximum_age_seconds < 0:
        errors.append("maximum_age_seconds_invalid")
    if isinstance(evaluation_time, bool) or not isinstance(evaluation_time, int) or evaluation_time < 0:
        errors.append("evaluation_time_invalid")
    if not records:
        errors.append("time_records_empty")
    for i, item in enumerate(records):
        start, end = item.get("started_at"), item.get("completed_at")
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (start, end)):
            errors.append(f"timestamp_invalid:{i}")
            continue
        if end < start:
            errors.append(f"time_order_invalid:{i}")
        if isinstance(evaluation_time, int) and not isinstance(evaluation_time, bool) and end > evaluation_time:
            errors.append(f"future_timestamp:{i}")
        if (isinstance(evaluation_time, int) and not isinstance(evaluation_time, bool)
                and isinstance(maximum_age_seconds, int) and not isinstance(maximum_age_seconds, bool)
                and maximum_age_seconds >= 0 and evaluation_time - end > maximum_age_seconds):
            errors.append(f"evidence_stale:{i}")
    return {"stage": 397, "pass": not errors, "errors": errors,
            "record_count": len(records)}


def check_evaluator_separation(evaluations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 398: require declared evaluator identity distinct from producer identity."""
    errors: list[str] = []
    if not evaluations:
        errors.append("evaluations_empty")
    seen: set[str] = set()
    for i, item in enumerate(evaluations):
        artifact_id = item.get("artifact_id")
        producer = item.get("producer_id")
        evaluator = item.get("evaluator_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            errors.append(f"artifact_id_invalid:{i}")
        elif artifact_id in seen:
            errors.append(f"artifact_id_duplicate:{artifact_id}")
        else:
            seen.add(artifact_id)
        if not isinstance(producer, str) or not producer.strip():
            errors.append(f"producer_id_invalid:{i}")
        if not isinstance(evaluator, str) or not evaluator.strip():
            errors.append(f"evaluator_id_invalid:{i}")
        if isinstance(producer, str) and isinstance(evaluator, str) and producer.strip() and producer == evaluator:
            errors.append(f"evaluator_not_distinct:{artifact_id if isinstance(artifact_id, str) else i}")
    return {"stage": 398, "pass": not errors, "errors": errors,
            "evaluation_count": len(seen)}


def check_evidence_decision_consistency(decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 399: reject conflicting duplicate decisions for the same evidence key."""
    errors: list[str] = []
    by_key: dict[str, str] = {}
    if not decisions:
        errors.append("decisions_empty")
    for i, item in enumerate(decisions):
        key, decision = item.get("evidence_key"), item.get("decision")
        if not isinstance(key, str) or not key.strip():
            errors.append(f"evidence_key_invalid:{i}")
            continue
        if not isinstance(decision, str) or not decision.strip():
            errors.append(f"decision_invalid:{i}")
            continue
        if key in by_key and by_key[key] != decision:
            errors.append(f"conflicting_decision:{key}")
        else:
            by_key[key] = decision
    return {"stage": 399, "pass": not errors, "errors": errors,
            "unique_evidence_key_count": len(by_key)}


def evaluate_stages_396_400(*, provenance_records: Sequence[Mapping[str, Any]],
                            time_records: Sequence[Mapping[str, Any]],
                            maximum_age_seconds: int, evaluation_time: int,
                            evaluations: Sequence[Mapping[str, Any]],
                            decisions: Sequence[Mapping[str, Any]],
                            upstream_gates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 400: final readiness aggregation; never grants execution or promotion authority."""
    checks = [
        check_source_provenance_declarations(provenance_records),
        check_evidence_time_windows(time_records, maximum_age_seconds=maximum_age_seconds,
                                    evaluation_time=evaluation_time),
        check_evaluator_separation(evaluations),
        check_evidence_decision_consistency(decisions),
    ]
    errors: list[str] = []
    required = set(range(386, 396))
    observed: set[int] = set()
    seen_seals: set[str] = set()
    if not upstream_gates:
        errors.append("upstream_gates_empty")
    for i, gate in enumerate(upstream_gates):
        stage, status, seal = gate.get("stage"), gate.get("status"), gate.get("seal")
        if isinstance(stage, bool) or not isinstance(stage, int):
            errors.append(f"upstream_stage_invalid:{i}")
            continue
        if stage in observed:
            errors.append(f"upstream_stage_duplicate:{stage}")
        observed.add(stage)
        if status != "PASS":
            errors.append(f"upstream_gate_not_pass:{stage}")
        if not isinstance(seal, str) or not _HEX64.fullmatch(seal):
            errors.append(f"upstream_seal_invalid:{stage}")
        elif seal in seen_seals:
            errors.append(f"upstream_seal_duplicate:{stage}")
        else:
            seen_seals.add(seal)
    errors.extend(f"upstream_stage_missing:{x}" for x in sorted(required - observed))
    errors.extend(f"upstream_stage_unexpected:{x}" for x in sorted(observed - required))
    all_pass = all(x["pass"] for x in checks) and not errors
    payload = {"checks": checks, "upstream_errors": errors, "all_pass": all_pass,
               "proposal_only": True, "execution_authorized": False,
               "promotion_authorized": False}
    return {"stage": 400, "status": "PASS" if all_pass else "BLOCKED",
            "checks": checks, "upstream_errors": errors, "seal": _seal(payload),
            "proposal_only": True, "execution_authorized": False,
            "promotion_authorized": False}
