"""Evidence-package integrity declarations (Stages 601-610).

This validates caller-supplied metadata only. It does not hash files, authenticate
signatures, verify storage, enforce access controls, or certify evidence truth.
"""
from __future__ import annotations

from datetime import datetime, timezone

REQUIRED = (
    "package_ref", "package_owner_ref", "artifacts", "evidence_refs",
    "lineage_edges", "created_at", "retention_policy_ref", "retention_expires_at",
    "access_classification", "redaction_status", "export_status",
    "consistency_check_ref", "automatic_export", "external_disclosure",
)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _unique_text_list(value, *, allow_empty=False):
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_text(item) for item in value)
        and len(value) == len(set(value))
    )


def _artifacts_valid(value):
    if not isinstance(value, list) or not value:
        return False
    required = ("artifact_ref", "media_type", "digest_algorithm", "digest_value")
    refs = []
    for item in value:
        if not isinstance(item, dict) or any(not _text(item.get(k)) for k in required):
            return False
        if item.get("digest_verified") is not False:
            return False
        refs.append(item["artifact_ref"])
    return len(refs) == len(set(refs))


def _lineage_valid(value, artifact_refs):
    if not isinstance(value, list):
        return False
    seen = set()
    for edge in value:
        if not isinstance(edge, dict):
            return False
        source, target, relation = (
            edge.get("source_ref"), edge.get("target_ref"), edge.get("relation")
        )
        if not all(_text(x) for x in (source, target, relation)):
            return False
        if source not in artifact_refs or target not in artifact_refs or source == target:
            return False
        key = (source, target, relation)
        if key in seen:
            return False
        seen.add(key)
    return True


def validate_evidence_package(record, *, now=None):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}

    missing = [key for key in REQUIRED if key not in record or record[key] is None]
    issues = []
    for field in ("package_ref", "package_owner_ref", "retention_policy_ref",
                  "consistency_check_ref"):
        if not _text(record.get(field)):
            issues.append(f"{field}_invalid")

    artifacts = record.get("artifacts")
    artifact_refs = {
        item.get("artifact_ref") for item in artifacts
        if isinstance(item, dict) and _text(item.get("artifact_ref"))
    } if isinstance(artifacts, list) else set()
    if not _artifacts_valid(artifacts):
        issues.append("artifacts_invalid")

    if not _unique_text_list(record.get("evidence_refs")):
        issues.append("evidence_refs_invalid")
    elif not artifact_refs.issubset(set(record["evidence_refs"])):
        issues.append("artifact_evidence_reference_mismatch")

    if not _lineage_valid(record.get("lineage_edges"), artifact_refs):
        issues.append("lineage_edges_invalid")

    created = _timestamp(record.get("created_at"))
    expires = _timestamp(record.get("retention_expires_at"))
    if created is None:
        issues.append("created_at_invalid")
    if expires is None:
        issues.append("retention_expires_at_invalid")
    if created is not None and expires is not None and expires <= created:
        issues.append("retention_window_invalid")

    current = now if now is not None else datetime.now(timezone.utc)
    if isinstance(current, str):
        current = _timestamp(current)
    elif isinstance(current, datetime) and current.tzinfo is not None:
        current = current.astimezone(timezone.utc)
    else:
        current = None
    if current is None:
        issues.append("now_invalid")
    elif expires is not None and expires <= current:
        issues.append("retention_expired")

    if record.get("access_classification") not in (
        "PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"
    ):
        issues.append("access_classification_invalid")
    if record.get("redaction_status") not in ("NOT_REQUIRED_DECLARED", "REDACTED_DECLARED"):
        issues.append("redaction_status_invalid")
    if record.get("export_status") not in ("NOT_EXPORTED", "LOCAL_PACKAGE_DECLARED"):
        issues.append("export_status_invalid")
    if record.get("automatic_export") is not False:
        issues.append("automatic_export_must_be_false")
    if record.get("external_disclosure") is not False:
        issues.append("external_disclosure_must_be_false")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {
        "status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
        "artifact_bytes_verified": False,
        "digest_values_verified": False,
        "lineage_truth_verified": False,
        "retention_enforcement_verified": False,
        "access_controls_enforced": False,
        "redaction_effectiveness_verified": False,
    }


def stage_610_evidence_package_gate(record, *, now=None):
    result = validate_evidence_package(record, now=now)
    return {
        **result,
        "gate": "BLOCKED" if result["status"] == "BLOCKED" else "READY_FOR_INDEPENDENT_REVIEW",
        "automatic_export": False,
        "external_disclosure": False,
        "execution_authorized": False,
        "release_authorized": False,
    }
