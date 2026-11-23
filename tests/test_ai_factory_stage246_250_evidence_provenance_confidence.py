import hashlib
import json
from datetime import datetime, timedelta, timezone

from core.ai_factory_stage246_250_evidence_provenance_confidence import (
    stage246_provenance_chain, stage247_source_corroboration,
    stage248_uncertainty_bound, stage249_evidence_sufficiency,
    stage250_evidence_review_gate,
)

GENESIS = "a" * 64
EVIDENCE = "b" * 64


def _events():
    previous = GENESIS
    rows = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(2):
        body = {
            "event_id": f"event-{i}", "source_id": f"source-{i}",
            "issuer_id": f"issuer-{i}", "evidence_digest": EVIDENCE,
            "previous_digest": previous,
            "recorded_at": (base + timedelta(minutes=i + 1)).isoformat(),
        }
        body["event_digest"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        previous = body["event_digest"]
        rows.append(body)
    return rows


def _pipeline():
    provenance = stage246_provenance_chain(events=_events(), genesis_digest=GENESIS)
    corroboration = stage247_source_corroboration(provenance=provenance)
    uncertainty = stage248_uncertainty_bound(
        estimate=0.2, lower_bound=0.1, upper_bound=0.3, confidence_level=0.95,
        sample_count=20, chain_digest=provenance["chain_digest"])
    sufficiency = stage249_evidence_sufficiency(
        corroboration=corroboration, uncertainty=uncertainty, coverage=1.0,
        evidence_age_seconds=10, maximum_age_seconds=300)
    return provenance, corroboration, uncertainty, sufficiency


def test_246_validates_ordered_content_addressed_chain():
    result = stage246_provenance_chain(events=_events(), genesis_digest=GENESIS)
    assert result["status"] == "PROVENANCE_CHAIN_VALID"
    assert result["event_count"] == 2
    assert result["source_count"] == result["issuer_count"] == 2
    assert result["task_execution_authorized"] is False
    assert stage246_provenance_chain(events=_events(), genesis_digest="bad")["status"] == "INSUFFICIENT_EVIDENCE"


def test_246_rejects_tampering_broken_links_duplicate_ids_and_bad_time():
    rows = _events()
    rows[0]["issuer_id"] = "tampered"
    assert stage246_provenance_chain(events=rows, genesis_digest=GENESIS)["status"] == "INSUFFICIENT_EVIDENCE"
    rows = _events()
    rows[1]["previous_digest"] = GENESIS
    assert stage246_provenance_chain(events=rows, genesis_digest=GENESIS)["status"] == "INSUFFICIENT_EVIDENCE"
    rows = _events()
    rows[1]["event_id"] = rows[0]["event_id"]
    assert stage246_provenance_chain(events=rows, genesis_digest=GENESIS)["status"] == "INSUFFICIENT_EVIDENCE"
    rows = _events()
    rows[1]["recorded_at"] = rows[0]["recorded_at"]
    assert stage246_provenance_chain(events=rows, genesis_digest=GENESIS)["status"] == "INSUFFICIENT_EVIDENCE"


def test_247_requires_distinct_declared_sources_and_issuers():
    provenance, _, _, _ = _pipeline()
    assert stage247_source_corroboration(provenance=provenance)["status"] == "CORROBORATION_SUPPORTED"
    assert stage247_source_corroboration(provenance=provenance, minimum_issuers=3)["status"] == "CORROBORATION_INSUFFICIENT"
    assert stage247_source_corroboration(provenance={**provenance, "event_count": 99})["status"] == "INSUFFICIENT_EVIDENCE"


def test_248_requires_positive_lower_bound_and_ordered_interval():
    provenance, _, _, _ = _pipeline()
    args = {"estimate": 0.2, "lower_bound": 0.1, "upper_bound": 0.3,
            "confidence_level": 0.95, "sample_count": 20,
            "chain_digest": provenance["chain_digest"]}
    assert stage248_uncertainty_bound(**args)["status"] == "UNCERTAINTY_BOUNDED"
    assert stage248_uncertainty_bound(**{**args, "lower_bound": -0.1})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage248_uncertainty_bound(**{**args, "sample_count": 1})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage248_uncertainty_bound(**{**args, "confidence_level": 1.0})["status"] == "INSUFFICIENT_EVIDENCE"


def test_249_requires_complete_fresh_linked_evidence():
    provenance, corroboration, uncertainty, _ = _pipeline()
    args = {"corroboration": corroboration, "uncertainty": uncertainty,
            "coverage": 1.0, "evidence_age_seconds": 10, "maximum_age_seconds": 300}
    assert stage249_evidence_sufficiency(**args)["status"] == "EVIDENCE_SUFFICIENT_FOR_REVIEW"
    assert stage249_evidence_sufficiency(**{**args, "coverage": 0.9})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage249_evidence_sufficiency(**{**args, "evidence_age_seconds": 301})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage249_evidence_sufficiency(**{**args, "uncertainty": {**uncertainty, "chain_digest": "c" * 64}})["status"] == "INSUFFICIENT_EVIDENCE"


def test_250_combines_integrity_checked_review_only_evidence():
    provenance, corroboration, uncertainty, sufficiency = _pipeline()
    result = stage250_evidence_review_gate(
        provenance=provenance, corroboration=corroboration,
        uncertainty=uncertainty, sufficiency=sufficiency)
    assert result["status"] == "EVIDENCE_READY_FOR_SEPARATE_REVIEW"
    assert result["passed_stages"] == [246, 247, 248, 249]
    assert result["task_execution_authorized"] is False
    assert result["model_change_authorized"] is False
    assert result["hold_release_authorized"] is False
    assert stage250_evidence_review_gate(
        provenance=provenance, corroboration=corroboration,
        uncertainty=uncertainty, sufficiency={**sufficiency, "coverage": 0.5}
    )["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage250_evidence_review_gate(
        provenance=provenance, corroboration=corroboration,
        uncertainty=uncertainty, sufficiency=sufficiency, held=None
    )["status"] == "INSUFFICIENT_EVIDENCE"
