"""Proposal-only auditability and evidence-lineage gates for AI Factory stages 406-410."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def check_evidence_lineage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 406: require explicit source, producer, timestamp, and digest for each evidence item."""
    errors: list[str] = []
    seen: set[str] = set()
    if not records:
        errors.append("lineage_records_empty")
    for i, item in enumerate(records):
        eid = item.get("evidence_id")
        if not isinstance(eid, str) or not eid.strip():
            errors.append(f"evidence_id_invalid:{i}")
        elif eid in seen:
            errors.append(f"evidence_id_duplicate:{eid}")
        else:
            seen.add(eid)
        for field in ("source_id", "producer_id"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field}_missing:{eid if isinstance(eid, str) else i}")
        timestamp = item.get("created_at")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            errors.append(f"created_at_invalid:{eid if isinstance(eid, str) else i}")
        digest = item.get("content_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"content_sha256_invalid:{eid if isinstance(eid, str) else i}")
    return {"stage": 406, "pass": not errors, "errors": errors, "record_count": len(seen)}


def check_audit_event_chain(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 407: validate a contiguous, uniquely identified, explicitly linked event sequence."""
    errors: list[str] = []
    seen: set[str] = set()
    if not events:
        errors.append("audit_events_empty")
    previous = None
    for i, event in enumerate(events):
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            errors.append(f"audit_event_id_invalid:{i}")
        elif event_id in seen:
            errors.append(f"audit_event_duplicate:{event_id}")
        else:
            seen.add(event_id)
        sequence = event.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence != i:
            errors.append(f"audit_sequence_invalid:{i}")
        link = event.get("previous_event_id")
        expected = None if i == 0 else previous
        if link != expected:
            errors.append(f"audit_link_mismatch:{i}")
        previous = event_id if isinstance(event_id, str) else None
    return {"stage": 407, "pass": not errors, "errors": errors, "event_count": len(seen)}


def check_replay_and_duplicate_evidence(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 408: reject repeated evidence IDs and repeated caller-declared fingerprints."""
    errors: list[str] = []
    ids: set[str] = set()
    fingerprints: set[str] = set()
    if not records:
        errors.append("replay_records_empty")
    for i, item in enumerate(records):
        eid, fingerprint = item.get("evidence_id"), item.get("fingerprint")
        if not isinstance(eid, str) or not eid.strip():
            errors.append(f"replay_evidence_id_invalid:{i}")
        elif eid in ids:
            errors.append(f"replay_evidence_id_duplicate:{eid}")
        else:
            ids.add(eid)
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            errors.append(f"replay_fingerprint_missing:{eid if isinstance(eid, str) else i}")
        elif fingerprint in fingerprints:
            errors.append(f"replay_fingerprint_duplicate:{fingerprint}")
        else:
            fingerprints.add(fingerprint)
    return {"stage": 408, "pass": not errors, "errors": errors,
            "unique_id_count": len(ids), "unique_fingerprint_count": len(fingerprints)}


def check_evaluator_separation(assignments: Sequence[Mapping[str, Any]], *,
                               required_scopes: Sequence[str]) -> dict[str, Any]:
    """Stage 409: require explicit evaluator/producer separation for every declared scope."""
    errors: list[str] = []
    seen: set[str] = set()
    required = list(required_scopes)
    if not required or any(not isinstance(x, str) or not x.strip() for x in required):
        errors.append("required_scopes_invalid")
    if len(set(required)) != len(required):
        errors.append("required_scopes_duplicate")
    if not assignments:
        errors.append("evaluator_assignments_empty")
    for i, item in enumerate(assignments):
        scope, producer, evaluator, attested = (
            item.get("scope"), item.get("producer_id"), item.get("evaluator_id"),
            item.get("separation_attested"))
        if not isinstance(scope, str) or not scope.strip():
            errors.append(f"evaluator_scope_invalid:{i}")
            continue
        if scope in seen:
            errors.append(f"evaluator_scope_duplicate:{scope}")
        seen.add(scope)
        if not isinstance(producer, str) or not producer.strip():
            errors.append(f"producer_id_missing:{scope}")
        if not isinstance(evaluator, str) or not evaluator.strip():
            errors.append(f"evaluator_id_missing:{scope}")
        elif isinstance(producer, str) and evaluator == producer:
            errors.append(f"evaluator_not_independent_by_declaration:{scope}")
        if attested is not True:
            errors.append(f"separation_attestation_missing:{scope}")
    errors.extend(f"evaluator_scope_missing:{x}" for x in sorted(set(required) - seen))
    errors.extend(f"evaluator_scope_unexpected:{x}" for x in sorted(seen - set(required)))
    return {"stage": 409, "pass": not errors, "errors": errors,
            "required_scope_count": len(required), "assigned_scope_count": len(seen)}


def evaluate_stages_406_410(*, lineage_records: Sequence[Mapping[str, Any]],
                            audit_events: Sequence[Mapping[str, Any]],
                            replay_records: Sequence[Mapping[str, Any]],
                            evaluator_assignments: Sequence[Mapping[str, Any]],
                            required_scopes: Sequence[str]) -> dict[str, Any]:
    """Stage 410: aggregate auditability readiness; never authorizes execution or promotion."""
    checks = [
        check_evidence_lineage(lineage_records),
        check_audit_event_chain(audit_events),
        check_replay_and_duplicate_evidence(replay_records),
        check_evaluator_separation(evaluator_assignments, required_scopes=required_scopes),
    ]
    all_pass = all(check["pass"] for check in checks)
    payload = {"checks": checks, "all_pass": all_pass, "proposal_only": True,
               "execution_authorized": False, "promotion_authorized": False}
    return {"stage": 410, "status": "PASS" if all_pass else "BLOCKED",
            "checks": checks, "seal": _seal(payload), "proposal_only": True,
            "execution_authorized": False, "promotion_authorized": False}
