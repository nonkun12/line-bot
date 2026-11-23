"""Stages 246-250: provenance, corroboration, uncertainty and evidence sufficiency.

Deterministic proposal-only validators. They do not authenticate issuers, fetch artifacts,
run experiments, mutate models, or grant execution authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from datetime import datetime
from typing import Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_FALSE = {
    "proposal_only": True, "task_execution_authorized": False,
    "experiment_execution_authorized": False, "model_change_authorized": False,
    "merge_deploy_authorized": False, "hold_release_authorized": False,
}


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _out(payload):
    result = {**payload, **_FALSE}
    canonical = {k: v for k, v in result.items() if k != "result_digest"}
    result["result_digest"] = sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return result


def _valid(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
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


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def stage246_provenance_chain(*, events: Sequence[Mapping], genesis_digest: str, held: bool = False):
    """Validate a content-addressed, ordered evidence-event chain (not a digital signature)."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events or not _digest(genesis_digest):
        return _blocked("events and a valid genesis digest are required")
    previous, ids, sources, issuers, times = genesis_digest, set(), set(), set(), []
    for event in events:
        if not isinstance(event, Mapping):
            return _blocked("each event must be a mapping")
        event_id, source_id, issuer_id = event.get("event_id"), event.get("source_id"), event.get("issuer_id")
        evidence_digest, recorded_at = event.get("evidence_digest"), event.get("recorded_at")
        if any(not isinstance(x, str) or not x.strip() for x in (event_id, source_id, issuer_id)):
            return _blocked("event, source and issuer IDs are required")
        if event_id in ids or not _digest(evidence_digest) or event.get("previous_digest") != previous:
            return _blocked("duplicate event, invalid evidence digest or broken chain link")
        parsed = _timestamp(recorded_at)
        if parsed is None or (times and parsed <= times[-1]):
            return _blocked("event timestamps must be timezone-aware and strictly increasing")
        body = {k: event.get(k) for k in ("event_id", "source_id", "issuer_id", "evidence_digest", "previous_digest", "recorded_at")}
        expected = sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if event.get("event_digest") != expected:
            return _blocked("event digest does not match canonical event content")
        ids.add(event_id); sources.add(source_id); issuers.add(issuer_id); times.append(parsed)
        previous = expected
    return _out({
        "status": "PROVENANCE_CHAIN_VALID", "event_count": len(events),
        "source_count": len(sources), "issuer_count": len(issuers),
        "chain_digest": previous,
    })


def stage247_source_corroboration(*, provenance: Mapping, minimum_sources: int = 2,
                                  minimum_issuers: int = 2, held: bool = False):
    """Require multiple declared sources and issuers; identity independence remains unproven."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _valid(provenance, "PROVENANCE_CHAIN_VALID"):
        return _blocked("valid Stage246 provenance result is required")
    if (not isinstance(minimum_sources, int) or isinstance(minimum_sources, bool) or minimum_sources < 2
            or not isinstance(minimum_issuers, int) or isinstance(minimum_issuers, bool) or minimum_issuers < 2):
        return _blocked("minimum source and issuer counts must be at least two")
    supported = provenance["source_count"] >= minimum_sources and provenance["issuer_count"] >= minimum_issuers
    return _out({
        "status": "CORROBORATION_SUPPORTED" if supported else "CORROBORATION_INSUFFICIENT",
        "chain_digest": provenance["chain_digest"], "source_count": provenance["source_count"],
        "issuer_count": provenance["issuer_count"], "minimum_sources": minimum_sources,
        "minimum_issuers": minimum_issuers,
    })


def stage248_uncertainty_bound(*, estimate: float, lower_bound: float, upper_bound: float,
                               confidence_level: float, sample_count: int,
                               chain_digest: str, held: bool = False):
    """Require a finite ordered interval, adequate sample count and positive lower bound."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not all(_finite(x) for x in (estimate, lower_bound, upper_bound, confidence_level))
            or lower_bound > estimate or estimate > upper_bound or lower_bound <= 0
            or not 0.90 <= confidence_level < 1.0
            or not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 5
            or not _digest(chain_digest)):
        return _blocked("invalid uncertainty interval, confidence, sample count or provenance link")
    return _out({
        "status": "UNCERTAINTY_BOUNDED", "estimate": estimate, "lower_bound": lower_bound,
        "upper_bound": upper_bound, "confidence_level": confidence_level,
        "sample_count": sample_count, "chain_digest": chain_digest,
    })


def stage249_evidence_sufficiency(*, corroboration: Mapping, uncertainty: Mapping,
                                  coverage: float, evidence_age_seconds: float,
                                  maximum_age_seconds: float, held: bool = False):
    """Gate evidence coverage and freshness while preserving its provenance link."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _valid(corroboration, "CORROBORATION_SUPPORTED") or not _valid(uncertainty, "UNCERTAINTY_BOUNDED"):
        return _blocked("supported corroboration and bounded uncertainty are required")
    if (not _finite(coverage) or coverage != 1.0 or not _finite(evidence_age_seconds)
            or not _finite(maximum_age_seconds) or evidence_age_seconds < 0
            or maximum_age_seconds <= 0 or evidence_age_seconds > maximum_age_seconds
            or corroboration["chain_digest"] != uncertainty["chain_digest"]):
        return _blocked("coverage, freshness or provenance linkage failed")
    return _out({
        "status": "EVIDENCE_SUFFICIENT_FOR_REVIEW", "chain_digest": uncertainty["chain_digest"],
        "coverage": coverage, "evidence_age_seconds": evidence_age_seconds,
        "maximum_age_seconds": maximum_age_seconds,
    })


def stage250_evidence_review_gate(*, provenance: Mapping, corroboration: Mapping,
                                  uncertainty: Mapping, sufficiency: Mapping, held: bool = False):
    """Combine verified structures into a separate-review recommendation only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    expected = (
        (provenance, "PROVENANCE_CHAIN_VALID"),
        (corroboration, "CORROBORATION_SUPPORTED"),
        (uncertainty, "UNCERTAINTY_BOUNDED"),
        (sufficiency, "EVIDENCE_SUFFICIENT_FOR_REVIEW"),
    )
    if any(not _valid(result, status) for result, status in expected):
        return _blocked("one or more evidence stages failed integrity or status validation")
    digests = {provenance["chain_digest"], corroboration["chain_digest"],
               uncertainty["chain_digest"], sufficiency["chain_digest"]}
    if len(digests) != 1:
        return _blocked("evidence chain identity mismatch")
    return _out({
        "status": "EVIDENCE_READY_FOR_SEPARATE_REVIEW", "chain_digest": next(iter(digests)),
        "passed_stages": [246, 247, 248, 249],
        "required_next_step": "independent review and separate explicit authorization",
        "asi_or_rsi_claim": False,
    })
