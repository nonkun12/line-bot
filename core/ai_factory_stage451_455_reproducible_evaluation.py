"""Reproducibility and auditability controls for AI Factory stages 451-455."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_run_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """451: validate the declared inputs needed to identify an evaluation run."""
    errors: list[str] = []
    for field in ("run_id", "protocol_id", "protocol_version", "task_set_id",
                  "evaluator_version", "model_id", "model_revision", "environment_id"):
        if not _text(manifest.get(field)):
            errors.append(f"manifest_{field}_missing")
    seed = manifest.get("random_seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        errors.append("manifest_random_seed_invalid")
    dependencies = manifest.get("dependency_versions")
    if not isinstance(dependencies, Mapping) or not dependencies:
        errors.append("manifest_dependency_versions_missing")
    elif any(not _text(k) or not _text(v) for k, v in dependencies.items()):
        errors.append("manifest_dependency_version_invalid")
    return {"stage": 451, "pass": not errors, "errors": errors}


def check_rerun_equivalence(first: Sequence[Mapping[str, Any]],
                            second: Sequence[Mapping[str, Any]], *,
                            score_tolerance: float = 0.0) -> dict[str, Any]:
    """452: compare task coverage, output digests, and scores across two declared runs."""
    errors: list[str] = []
    if (not isinstance(score_tolerance, (int, float)) or isinstance(score_tolerance, bool)
            or score_tolerance < 0):
        errors.append("rerun_score_tolerance_invalid")
        tolerance = 0.0
    else:
        tolerance = float(score_tolerance)

    def index(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for i, row in enumerate(rows):
            tid = row.get("task_id")
            if not _text(tid):
                errors.append(f"{label}_task_id_invalid:{i}")
            elif tid in result:
                errors.append(f"{label}_task_duplicate:{tid}")
            else:
                result[tid] = row
            digest = row.get("output_sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                errors.append(f"{label}_output_digest_invalid:{tid if _text(tid) else i}")
            score = row.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                errors.append(f"{label}_score_invalid:{tid if _text(tid) else i}")
        return result

    a, b = index(first, "first"), index(second, "second")
    if set(a) != set(b):
        errors.append("rerun_task_coverage_mismatch")
    for tid in sorted(set(a) & set(b)):
        if a[tid].get("output_sha256") != b[tid].get("output_sha256"):
            errors.append(f"rerun_output_mismatch:{tid}")
        x, y = a[tid].get("score"), b[tid].get("score")
        if (isinstance(x, (int, float)) and not isinstance(x, bool)
                and isinstance(y, (int, float)) and not isinstance(y, bool)
                and abs(x - y) > tolerance):
            errors.append(f"rerun_score_mismatch:{tid}")
    return {"stage": 452, "pass": not errors, "errors": errors,
            "first_task_count": len(a), "second_task_count": len(b),
            "score_tolerance": tolerance}


def check_evaluator_pinning(manifest: Mapping[str, Any],
                            expected: Mapping[str, Any]) -> dict[str, Any]:
    """453: require exact evaluator/model/environment revision matches."""
    errors: list[str] = []
    for field in ("evaluator_version", "model_id", "model_revision", "environment_id",
                  "protocol_id", "protocol_version", "task_set_id"):
        if not _text(expected.get(field)):
            errors.append(f"expected_{field}_missing")
        elif manifest.get(field) != expected.get(field):
            errors.append(f"pin_{field}_mismatch")
    return {"stage": 453, "pass": not errors, "errors": errors}


def check_audit_chain(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """454: validate ordered event sequence and hash-linked declarations."""
    errors: list[str] = []
    previous = "0" * 64
    expected_sequence = 1
    for i, event in enumerate(events):
        sequence = event.get("sequence")
        if sequence != expected_sequence:
            errors.append(f"audit_sequence_invalid:{i}")
        if event.get("previous_digest") != previous:
            errors.append(f"audit_previous_digest_mismatch:{i}")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            errors.append(f"audit_payload_invalid:{i}")
            payload = {}
        expected_digest = _canonical_digest({"sequence": sequence,
                                             "previous_digest": event.get("previous_digest"),
                                             "payload": payload})
        if event.get("event_digest") != expected_digest:
            errors.append(f"audit_event_digest_mismatch:{i}")
        previous = event.get("event_digest") if _text(event.get("event_digest")) else ""
        expected_sequence += 1
    if not events:
        errors.append("audit_chain_empty")
    return {"stage": 454, "pass": not errors, "errors": errors,
            "event_count": len(events), "terminal_digest": previous}


def build_audit_chain(payloads: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Create deterministic hash-linked event declarations for fixtures and local use."""
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    for sequence, payload in enumerate(payloads, start=1):
        digest = _canonical_digest({"sequence": sequence, "previous_digest": previous,
                                    "payload": payload})
        events.append({"sequence": sequence, "previous_digest": previous,
                       "payload": dict(payload), "event_digest": digest})
        previous = digest
    return events


def evaluate_stages_451_455(*, manifest: Mapping[str, Any],
                            expected_pins: Mapping[str, Any],
                            first_run: Sequence[Mapping[str, Any]],
                            second_run: Sequence[Mapping[str, Any]],
                            audit_events: Sequence[Mapping[str, Any]],
                            score_tolerance: float = 0.0) -> dict[str, Any]:
    """455: aggregate reproducibility readiness; never certifies actual provenance."""
    checks = [
        check_run_manifest(manifest),
        check_rerun_equivalence(first_run, second_run, score_tolerance=score_tolerance),
        check_evaluator_pinning(manifest, expected_pins),
        check_audit_chain(audit_events),
    ]
    passed = all(item["pass"] for item in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 455, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "seal": _canonical_digest(record),
            "provenance_verified": False, "reproducibility_certified": False,
            "execution_authorized": False, "promotion_authorized": False,
            "proposal_only": True}
