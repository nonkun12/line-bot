"""Proposal-only evaluation audit-trail declaration checks, stages 421-425."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def check_event_identity(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """421: unique event IDs, run IDs, and positive integer sequence numbers."""
    errors: list[str] = []
    ids: set[str] = set()
    seqs: set[tuple[str, int]] = set()
    if not events:
        errors.append("events_empty")
    for i, event in enumerate(events):
        eid, run = event.get("event_id"), event.get("run_id")
        seq = event.get("sequence")
        if not _text(eid):
            errors.append(f"event_id_invalid:{i}")
        elif eid in ids:
            errors.append(f"event_id_duplicate:{eid}")
        else:
            ids.add(eid)
        if not _text(run):
            errors.append(f"event_run_id_invalid:{i}")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            errors.append(f"event_sequence_invalid:{i}")
        elif _text(run):
            key = (run, seq)
            if key in seqs:
                errors.append(f"event_sequence_duplicate:{run}:{seq}")
            seqs.add(key)
    return {"stage": 421, "pass": not errors, "errors": errors, "event_count": len(ids)}


def check_event_order(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """422: require contiguous, strictly increasing sequence declarations per run."""
    errors: list[str] = []
    grouped: dict[str, list[int]] = {}
    for i, event in enumerate(events):
        run, seq = event.get("run_id"), event.get("sequence")
        if _text(run) and isinstance(seq, int) and not isinstance(seq, bool) and seq > 0:
            grouped.setdefault(run, []).append(seq)
        else:
            errors.append(f"event_order_input_invalid:{i}")
    for run, values in grouped.items():
        ordered = sorted(values)
        if ordered != list(range(1, len(ordered) + 1)):
            errors.append(f"event_sequence_gap_or_duplicate:{run}")
    return {"stage": 422, "pass": not errors, "errors": errors, "run_count": len(grouped)}


def check_record_integrity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """423: recompute canonical payload digests and reject missing or conflicting IDs."""
    errors: list[str] = []
    seen: set[str] = set()
    if not records:
        errors.append("records_empty")
    for i, record in enumerate(records):
        rid, payload, claimed = record.get("record_id"), record.get("payload"), record.get("sha256")
        if not _text(rid):
            errors.append(f"record_id_invalid:{i}")
        elif rid in seen:
            errors.append(f"record_id_duplicate:{rid}")
        else:
            seen.add(rid)
        if not isinstance(payload, Mapping):
            errors.append(f"record_payload_invalid:{i}")
            continue
        if not _digest(claimed):
            errors.append(f"record_digest_invalid:{i}")
        elif _hash(payload) != claimed:
            errors.append(f"record_digest_mismatch:{rid}")
    return {"stage": 423, "pass": not errors, "errors": errors, "record_count": len(seen)}


def check_actor_role_separation(assignments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """424: reject same declared actor for generator and evaluator in one assessment."""
    errors: list[str] = []
    seen: set[str] = set()
    if not assignments:
        errors.append("actor_assignments_empty")
    for i, item in enumerate(assignments):
        assessment = item.get("assessment_id")
        generator, evaluator = item.get("generator_actor"), item.get("evaluator_actor")
        if not _text(assessment):
            errors.append(f"assessment_id_invalid:{i}")
        elif assessment in seen:
            errors.append(f"assessment_duplicate:{assessment}")
        else:
            seen.add(assessment)
        if not _text(generator) or not _text(evaluator):
            errors.append(f"actor_identity_missing:{assessment if _text(assessment) else i}")
        elif generator == evaluator:
            errors.append(f"actor_role_conflict:{assessment}")
    return {"stage": 424, "pass": not errors, "errors": errors, "assessment_count": len(seen)}


def evaluate_stages_421_425(*, events: Sequence[Mapping[str, Any]],
                            records: Sequence[Mapping[str, Any]],
                            actor_assignments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """425: fail-closed audit-trail declaration gate; no authority is granted."""
    checks = [check_event_identity(events), check_event_order(events),
              check_record_integrity(records), check_actor_role_separation(actor_assignments)]
    errors: list[str] = []
    event_ids = {e.get("event_id") for e in events if _text(e.get("event_id"))}
    record_ids = {r.get("record_id") for r in records if _text(r.get("record_id"))}
    if not event_ids:
        errors.append("no_valid_event_identity")
    if not record_ids:
        errors.append("no_valid_record_identity")
    passed = all(c["pass"] for c in checks) and not errors
    payload = {"checks": checks, "errors": errors, "pass": passed,
               "proposal_only": True, "execution_authorized": False}
    return {"stage": 425, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _hash(payload),
            "proposal_only": True, "execution_authorized": False,
            "promotion_authorized": False}
