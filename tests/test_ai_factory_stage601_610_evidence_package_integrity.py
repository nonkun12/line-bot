import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "stage601", Path(__file__).parents[1] /
    "core/ai_factory_stage601_610_evidence_package_integrity.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def good():
    return {
        "package_ref": "package-1",
        "package_owner_ref": "owner-1",
        "artifacts": [
            {"artifact_ref": "artifact-a", "media_type": "text/plain",
             "digest_algorithm": "sha256", "digest_value": "declared-digest-a",
             "digest_verified": False},
            {"artifact_ref": "artifact-b", "media_type": "application/json",
             "digest_algorithm": "sha256", "digest_value": "declared-digest-b",
             "digest_verified": False},
        ],
        "evidence_refs": ["artifact-a", "artifact-b", "run-1"],
        "lineage_edges": [
            {"source_ref": "artifact-a", "target_ref": "artifact-b",
             "relation": "derived_from"}
        ],
        "created_at": "2026-11-23T00:00:00Z",
        "retention_policy_ref": "retention-policy-1",
        "retention_expires_at": "2027-11-23T00:00:00Z",
        "access_classification": "INTERNAL",
        "redaction_status": "REDACTED_DECLARED",
        "export_status": "NOT_EXPORTED",
        "consistency_check_ref": "consistency-check-1",
        "automatic_export": False,
        "external_disclosure": False,
    }


def test_complete_package_is_review_only_and_not_verified():
    result = m.stage_610_evidence_package_gate(
        good(), now=datetime(2026, 11, 24, tzinfo=timezone.utc)
    )
    assert result["status"] == "DECLARATIONS_COMPLETE"
    assert result["gate"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert result["artifact_bytes_verified"] is False
    assert result["digest_values_verified"] is False
    assert result["access_controls_enforced"] is False
    assert result["automatic_export"] is False
    assert result["execution_authorized"] is False


def test_missing_fields_and_expired_retention_block():
    record = good()
    del record["consistency_check_ref"]
    result = m.validate_evidence_package(
        record, now=datetime(2026, 11, 24, tzinfo=timezone.utc)
    )
    assert "consistency_check_ref" in result["missing"]
    record = good()
    result = m.validate_evidence_package(
        record, now=datetime(2027, 11, 24, tzinfo=timezone.utc)
    )
    assert "retention_expired" in result["issues"]


def test_bad_artifact_digest_metadata_and_duplicate_refs_block():
    for mutate in (
        lambda r: r["artifacts"][0].update(digest_value=""),
        lambda r: r["artifacts"][0].update(digest_verified=True),
        lambda r: r["artifacts"].append(dict(r["artifacts"][0])),
    ):
        record = good()
        mutate(record)
        assert m.validate_evidence_package(record)["status"] == "BLOCKED"


def test_evidence_and_lineage_must_resolve_to_artifacts():
    record = good()
    record["evidence_refs"] = ["artifact-a"]
    assert "artifact_evidence_reference_mismatch" in m.validate_evidence_package(record)["issues"]
    record = good()
    record["lineage_edges"][0]["target_ref"] = "unknown"
    assert "lineage_edges_invalid" in m.validate_evidence_package(record)["issues"]


def test_bad_timestamps_classification_and_retention_window_block():
    for field, value in (
        ("created_at", "2026-11-23"),
        ("retention_expires_at", "2026-11-22T00:00:00Z"),
        ("access_classification", "UNKNOWN"),
    ):
        record = good()
        record[field] = value
        assert m.validate_evidence_package(record)["status"] == "BLOCKED"


def test_export_and_disclosure_are_fail_closed():
    for field in ("automatic_export", "external_disclosure"):
        record = good()
        record[field] = True
        assert m.validate_evidence_package(record)["status"] == "BLOCKED"
