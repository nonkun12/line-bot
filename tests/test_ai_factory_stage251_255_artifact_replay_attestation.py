import hashlib

from core.ai_factory_stage251_255_artifact_replay_attestation import (
    stage251_verify_artifact_bytes, stage252_validate_key_lifecycle,
    stage253_replay_check, stage254_role_separation, stage255_attestation_review_gate,
)

NOW = "2026-11-23T08:00:00+09:00"
NONCE = "a" * 32


def _pipeline():
    payload = b"evidence artifact bytes"
    artifact = stage251_verify_artifact_bytes(
        package_id="pkg-001",
        artifacts=[{"artifact_id": "report", "content": payload,
                    "sha256": hashlib.sha256(payload).hexdigest()}],
    )
    keys = stage252_validate_key_lifecycle(
        key_records=[{
            "key_id": "key-1", "principal_id": "principal-issuer", "state": "active",
            "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z",
        }],
        evaluated_at=NOW,
    )
    replay = stage253_replay_check(
        nonce=NONCE, consumed_nonces=["b" * 32],
        issued_at="2026-11-23T07:00:00+09:00",
        expires_at="2026-11-23T09:00:00+09:00",
        evaluated_at=NOW, package_digest=artifact["package_digest"],
    )
    roles = stage254_role_separation(assignments={
        "issuer": "org-a", "evaluator": "org-b", "approver": "org-c",
    })
    return artifact, keys, replay, roles


def test_251_hashes_actual_artifact_bytes_and_rejects_tampering():
    payload = b"trusted bytes"
    result = stage251_verify_artifact_bytes(
        package_id="p", artifacts=[{"artifact_id": "a", "content": payload,
                                    "sha256": hashlib.sha256(payload).hexdigest()}])
    assert result["status"] == "ARTIFACT_BYTES_VERIFIED"
    assert result["artifacts"][0]["size_bytes"] == len(payload)
    assert result["task_execution_authorized"] is False
    assert stage251_verify_artifact_bytes(
        package_id="p", artifacts=[{"artifact_id": "a", "content": b"changed",
                                    "sha256": hashlib.sha256(payload).hexdigest()}]
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_251_requires_unique_artifact_ids_and_bytes():
    payload = b"x"
    row = {"artifact_id": "same", "content": payload, "sha256": hashlib.sha256(payload).hexdigest()}
    assert stage251_verify_artifact_bytes(package_id="p", artifacts=[row, row])["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage251_verify_artifact_bytes(
        package_id="p", artifacts=[{"artifact_id": "a", "content": "not bytes",
                                    "sha256": hashlib.sha256(payload).hexdigest()}]
    )["status"] == "INSUFFICIENT_EVIDENCE"


def test_252_checks_key_lifecycle_and_active_window():
    records = [{
        "key_id": "k1", "principal_id": "p1", "state": "active",
        "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z",
    }]
    assert stage252_validate_key_lifecycle(key_records=records, evaluated_at=NOW)["status"] == "KEY_LIFECYCLE_STRUCTURALLY_VALID"
    expired = [{**records[0], "valid_until": "2026-02-01T00:00:00Z"}]
    assert stage252_validate_key_lifecycle(key_records=expired, evaluated_at=NOW)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage252_validate_key_lifecycle(key_records=records + records, evaluated_at=NOW)["status"] == "INSUFFICIENT_EVIDENCE"


def test_253_rejects_replay_expiry_and_future_issue():
    args = {
        "nonce": NONCE, "consumed_nonces": ["b" * 32],
        "issued_at": "2026-11-23T07:00:00+09:00",
        "expires_at": "2026-11-23T09:00:00+09:00",
        "evaluated_at": NOW, "package_digest": "c" * 64,
    }
    assert stage253_replay_check(**args)["status"] == "REPLAY_CHECK_CLEAR"
    assert stage253_replay_check(**{**args, "consumed_nonces": [NONCE]})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage253_replay_check(**{**args, "expires_at": "2026-11-23T08:00:00+09:00"})["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage253_replay_check(**{**args, "issued_at": "2026-11-23T10:00:00+09:00"})["status"] == "INSUFFICIENT_EVIDENCE"


def test_254_requires_distinct_role_principals():
    assert stage254_role_separation(assignments={
        "issuer": "a", "evaluator": "b", "approver": "c"
    })["status"] == "ROLE_SEPARATION_DECLARED"
    assert stage254_role_separation(assignments={
        "issuer": "same", "evaluator": "same", "approver": "c"
    })["status"] == "INSUFFICIENT_EVIDENCE"


def test_255_only_recommends_separate_review_and_keeps_authority_false():
    artifact, keys, replay, roles = _pipeline()
    result = stage255_attestation_review_gate(
        artifact_result=artifact, key_result=keys, replay_result=replay, role_result=roles)
    assert result["status"] == "ATTESTATION_READY_FOR_SEPARATE_REVIEW"
    assert result["cryptographic_signature_verified"] is False
    assert result["durable_replay_registry_verified"] is False
    assert result["task_execution_authorized"] is False
    assert result["model_change_authorized"] is False
    assert result["hold_release_authorized"] is False
    assert stage255_attestation_review_gate(
        artifact_result=artifact, key_result=keys, replay_result={**replay, "package_digest": "d" * 64},
        role_result=roles)["status"] == "INSUFFICIENT_EVIDENCE"
    assert stage255_attestation_review_gate(
        artifact_result=artifact, key_result=keys, replay_result=replay,
        role_result=roles, held=None)["status"] == "INSUFFICIENT_EVIDENCE"
