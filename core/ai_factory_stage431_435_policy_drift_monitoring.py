"""Deterministic, proposal-only policy drift checks for AI Factory stages 431-435."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_policy_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """431: validate a uniquely versioned policy snapshot declaration."""
    errors: list[str] = []
    for field in ("policy_id", "version", "effective_at", "owner", "canonical_digest"):
        if not _text(snapshot.get(field)):
            errors.append(f"snapshot_{field}_missing")
    digest = snapshot.get("canonical_digest")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        errors.append("snapshot_digest_invalid")
    rules = snapshot.get("rules")
    if not isinstance(rules, list) or not rules:
        errors.append("snapshot_rules_empty_or_invalid")
    elif any(not isinstance(rule, Mapping) or not _text(rule.get("rule_id")) for rule in rules):
        errors.append("snapshot_rule_identity_invalid")
    elif len({rule.get("rule_id") for rule in rules}) != len(rules):
        errors.append("snapshot_rule_ids_duplicate")
    return {"stage": 431, "pass": not errors, "errors": errors}


def compare_policy_snapshots(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """432: enumerate added, removed, and changed rules between declared snapshots."""
    errors: list[str] = []
    prev_rules, curr_rules = previous.get("rules"), current.get("rules")
    if not isinstance(prev_rules, list) or not isinstance(curr_rules, list):
        return {"stage": 432, "pass": False, "errors": ["policy_rules_invalid"],
                "added": [], "removed": [], "changed": []}
    def index(items: list[Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in items:
            if not isinstance(item, Mapping) or not _text(item.get("rule_id")):
                errors.append("policy_rule_invalid")
                continue
            rid = item["rule_id"]
            if rid in result:
                errors.append(f"policy_rule_duplicate:{rid}")
            result[rid] = item
        return result
    old, new = index(prev_rules), index(curr_rules)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    if not _text(previous.get("version")) or not _text(current.get("version")):
        errors.append("policy_version_missing")
    return {"stage": 432, "pass": not errors, "errors": errors,
            "added": added, "removed": removed, "changed": changed,
            "has_drift": bool(added or removed or changed)}


def classify_policy_drift(diff: Mapping[str, Any], classifications: Mapping[str, str]) -> dict[str, Any]:
    """433: require explicit bounded risk labels for each changed rule identity."""
    errors: list[str] = []
    affected = set(diff.get("added", [])) | set(diff.get("removed", [])) | set(diff.get("changed", []))
    allowed = {"low", "medium", "high", "critical"}
    for rid in sorted(affected):
        label = classifications.get(rid)
        if label not in allowed:
            errors.append(f"drift_classification_missing_or_invalid:{rid}")
    extra = set(classifications) - affected
    if extra:
        errors.extend(f"drift_classification_unmatched:{rid}" for rid in sorted(extra))
    return {"stage": 433, "pass": not errors, "errors": errors,
            "affected_rule_count": len(affected)}


def check_drift_disposition(diff: Mapping[str, Any], classifications: Mapping[str, str],
                            dispositions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """434: require a traceable disposition for each drift; critical/high cannot be waived."""
    errors: list[str] = []
    affected = set(diff.get("added", [])) | set(diff.get("removed", [])) | set(diff.get("changed", []))
    for rid in sorted(affected):
        item = dispositions.get(rid)
        if not isinstance(item, Mapping):
            errors.append(f"drift_disposition_missing:{rid}")
            continue
        if not _text(item.get("decision_ref")) or not _text(item.get("owner")):
            errors.append(f"drift_disposition_trace_missing:{rid}")
        decision = item.get("decision")
        if decision not in ("accept_for_review", "reject", "defer"):
            errors.append(f"drift_disposition_invalid:{rid}")
        if classifications.get(rid) in ("high", "critical") and decision == "accept_for_review":
            errors.append(f"high_risk_drift_requires_escalation:{rid}")
    extra = set(dispositions) - affected
    errors.extend(f"drift_disposition_unmatched:{rid}" for rid in sorted(extra))
    return {"stage": 434, "pass": not errors, "errors": errors,
            "disposition_count": len(affected)}


def evaluate_stages_431_435(*, previous: Mapping[str, Any], current: Mapping[str, Any],
                            classifications: Mapping[str, str],
                            dispositions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """435: fail-closed policy drift readiness report, without applying policy changes."""
    snapshot = check_policy_snapshot(current)
    diff = compare_policy_snapshots(previous, current)
    classification = classify_policy_drift(diff, classifications)
    disposition = check_drift_disposition(diff, classifications, dispositions)
    checks = [snapshot, diff, classification, disposition]
    errors: list[str] = []
    if previous.get("policy_id") != current.get("policy_id"):
        errors.append("policy_identity_changed")
    if previous.get("version") == current.get("version"):
        errors.append("policy_version_not_advanced")
    passed = all(item["pass"] for item in checks) and not errors
    payload = {"checks": checks, "errors": errors, "pass": passed,
               "proposal_only": True, "policy_apply_authorized": False}
    return {"stage": 435, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _seal(payload),
            "proposal_only": True, "policy_apply_authorized": False,
            "execution_authorized": False, "promotion_authorized": False}
