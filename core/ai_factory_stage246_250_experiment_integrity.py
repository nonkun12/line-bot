"""Stages 246-250: protocol adherence, evaluator agreement, audit continuity and uncertainty.

Deterministic proposal-only evidence checks. No experiment or task is executed.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from typing import Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")


def _blocked(reason: str) -> dict:
    return {
        "status": "INSUFFICIENT_EVIDENCE",
        "reason": reason,
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
        "hold_release_authorized": False,
    }


def _out(payload: dict) -> dict:
    payload.update({
        "proposal_only": True,
        "task_execution_authorized": False,
        "experiment_execution_authorized": False,
        "model_change_authorized": False,
        "merge_deploy_authorized": False,
        "hold_release_authorized": False,
    })
    return payload


def _digest(value) -> bool:
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _finite(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def stage246_protocol_adherence(*, registered_digest: str, observed_digest: str,
                                deviations: Sequence[Mapping], held: bool = False):
    """Check protocol identity and require each deviation to be explicitly reviewed."""
    if held:
        return _blocked("HOLD is active")
    if not _digest(registered_digest) or not _digest(observed_digest):
        return _blocked("invalid registered or observed protocol digest")
    if not isinstance(deviations, Sequence) or isinstance(deviations, (str, bytes)):
        return _blocked("deviations must be a sequence")
    if registered_digest != observed_digest:
        return _out({"status": "PROTOCOL_DEVIATION", "unreviewed_deviations": ["protocol_digest_mismatch"]})
    unreviewed = []
    seen = set()
    for item in deviations:
        if not isinstance(item, Mapping):
            return _blocked("deviation record must be a mapping")
        deviation_id = item.get("deviation_id")
        evidence_digest = item.get("evidence_digest")
        if not isinstance(deviation_id, str) or not deviation_id.strip() or deviation_id in seen:
            return _blocked("missing or duplicate deviation ID")
        seen.add(deviation_id)
        if item.get("reviewed") is not True or not _digest(evidence_digest):
            unreviewed.append(deviation_id)
    return _out({
        "status": "PROTOCOL_ADHERENT" if not unreviewed else "PROTOCOL_DEVIATION",
        "deviation_count": len(deviations),
        "unreviewed_deviations": unreviewed,
    })


def stage247_evaluator_agreement(*, evaluations: Sequence[Mapping],
                                 minimum_evaluators: int = 2,
                                 max_score_spread: float = 0.05,
                                 held: bool = False):
    """Measure score spread across distinct evaluator IDs; does not prove independence."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(evaluations, Sequence) or isinstance(evaluations, (str, bytes))
            or not isinstance(minimum_evaluators, int) or isinstance(minimum_evaluators, bool)
            or minimum_evaluators < 2 or not _finite(max_score_spread)
            or max_score_spread < 0):
        return _blocked("invalid evaluator agreement inputs")
    by_id = {}
    for item in evaluations:
        if not isinstance(item, Mapping):
            return _blocked("evaluation must be a mapping")
        evaluator_id, score = item.get("evaluator_id"), item.get("score")
        if not isinstance(evaluator_id, str) or not evaluator_id.strip() or not _finite(score):
            return _blocked("invalid evaluator identity or score")
        if evaluator_id in by_id:
            return _blocked("duplicate evaluator identity")
        by_id[evaluator_id] = float(score)
    if len(by_id) < minimum_evaluators:
        return _blocked("insufficient distinct evaluators")
    spread = max(by_id.values()) - min(by_id.values())
    return _out({
        "status": "EVALUATORS_AGREE" if spread <= max_score_spread else "EVALUATOR_DISAGREEMENT",
        "evaluator_count": len(by_id),
        "score_spread": spread,
        "max_score_spread": float(max_score_spread),
        "evaluator_independence": "not established by distinct IDs",
    })


def stage248_validate_audit_chain(*, records: Sequence[Mapping], held: bool = False):
    """Validate a canonical SHA-256 chain over ordered audit records."""
    if held:
        return _blocked("HOLD is active")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
        return _blocked("audit records are required")
    previous = "0" * 64
    seen = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            return _blocked("audit record must be a mapping")
        record_id = record.get("record_id")
        supplied_previous = record.get("previous_digest")
        supplied_digest = record.get("record_digest")
        if not isinstance(record_id, str) or not record_id.strip() or record_id in seen:
            return _blocked("missing or duplicate audit record ID")
        if supplied_previous != previous:
            return _out({"status": "AUDIT_CHAIN_INVALID", "invalid_index": index,
                         "reason": "previous digest mismatch"})
        payload = {k: v for k, v in record.items() if k != "record_digest"}
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return _blocked("audit record is not canonical JSON data")
        expected = sha256(canonical.encode("utf-8")).hexdigest()
        if not _digest(supplied_digest) or supplied_digest != expected:
            return _out({"status": "AUDIT_CHAIN_INVALID", "invalid_index": index,
                         "reason": "record digest mismatch"})
        seen.add(record_id)
        previous = supplied_digest
    return _out({"status": "AUDIT_CHAIN_VALID", "record_count": len(records),
                 "terminal_digest": previous})


def stage249_uncertainty_completeness(*, estimates: Sequence[Mapping],
                                      required_metrics: Sequence[str],
                                      held: bool = False):
    """Require finite point estimates and ordered, bounded uncertainty intervals."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(estimates, Sequence) or isinstance(estimates, (str, bytes))
            or not isinstance(required_metrics, Sequence)
            or isinstance(required_metrics, (str, bytes)) or not required_metrics):
        return _blocked("estimates and required metrics are required")
    indexed = {}
    for item in estimates:
        if not isinstance(item, Mapping):
            return _blocked("estimate must be a mapping")
        metric = item.get("metric")
        point, lower, upper = item.get("point"), item.get("lower"), item.get("upper")
        if not isinstance(metric, str) or not metric.strip() or metric in indexed:
            return _blocked("missing or duplicate metric")
        if not all(_finite(x) for x in (point, lower, upper)) or lower > point or point > upper:
            return _blocked("invalid or unordered uncertainty interval")
        indexed[metric] = {"point": float(point), "lower": float(lower), "upper": float(upper)}
    if any(not isinstance(m, str) or not m.strip() for m in required_metrics):
        return _blocked("invalid required metric name")
    missing = sorted(set(required_metrics) - set(indexed))
    if missing:
        return _out({"status": "UNCERTAINTY_INCOMPLETE", "missing_metrics": missing})
    return _out({"status": "UNCERTAINTY_COMPLETE",
                 "metric_count": len(indexed), "required_metric_count": len(set(required_metrics)),
                 "intervals": indexed})


def stage250_experiment_integrity_gate(*, protocol: Mapping, evaluator: Mapping,
                                       audit: Mapping, uncertainty: Mapping,
                                       held: bool = False):
    """Combine integrity evidence into a separate-review recommendation only."""
    if held:
        return _blocked("HOLD is active")
    required = {
        "protocol": (protocol, {"PROTOCOL_ADHERENT"}),
        "evaluator": (evaluator, {"EVALUATORS_AGREE"}),
        "audit": (audit, {"AUDIT_CHAIN_VALID"}),
        "uncertainty": (uncertainty, {"UNCERTAINTY_COMPLETE"}),
    }
    failed = [name for name, (result, statuses) in required.items()
              if not isinstance(result, Mapping) or result.get("status") not in statuses]
    if failed:
        return _blocked("integrity prerequisites failed: " + ",".join(failed))
    return _out({
        "status": "READY_FOR_SEPARATE_REVIEW",
        "validated_domains": sorted(required),
        "required_next_step": "independent review outside this module",
        "authority": "evidence summary only; no experiment or runtime authority",
    })
