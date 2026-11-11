from datetime import datetime, timezone
import hashlib
import hmac

import pytest

from core.orca_task_approval import build_approval_payload, is_valid_line_user_id


USER = "U0123456789abcdef0123456789abcdef"
SECRET = "test-secret-that-is-at-least-thirty-two-bytes"


def test_only_verified_line_user_id_is_accepted():
    assert is_valid_line_user_id(USER)
    assert not is_valid_line_user_id("not-a-line-user")
    assert not is_valid_line_user_id(None)


def test_approval_signature_binds_task_text_and_identity():
    now = datetime(2026, 11, 11, 1, 2, 3, tzinfo=timezone.utc)
    payload = build_approval_payload(
        "line-task-1", "アプリ開発: sample", USER, SECRET, now=now
    )
    expected_hash = hashlib.sha256("アプリ開発: sample".encode()).hexdigest()
    assert payload["request_hash"] == expected_hash
    canonical = "\n".join((
        "v1", "line-task-1", expected_hash, USER,
        payload["issued_at"], payload["expires_at"], payload["nonce"],
    ))
    expected = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(payload["signature"], expected)
    assert payload["expires_at"] == "2026-11-11T01:07:03Z"
    assert len(payload["nonce"]) == 32


def test_approval_signature_changes_when_task_or_approver_changes():
    now = datetime(2026, 11, 11, 1, 2, 3, tzinfo=timezone.utc)
    first = build_approval_payload("line-task-1", "アプリ開発: sample", USER, SECRET, now=now)
    second = build_approval_payload("line-task-2", "アプリ開発: sample", USER, SECRET, now=now)
    other_user = "U" + "a" * 32
    third = build_approval_payload("line-task-1", "アプリ開発: sample", other_user, SECRET, now=now)
    assert first["signature"] != second["signature"]
    assert first["signature"] != third["signature"]
    assert first["nonce"] != second["nonce"]


@pytest.mark.parametrize("task_id,user_id,secret", [
    ("../task", USER, SECRET),
    ("task", "invalid", SECRET),
    ("task", USER, ""),
    ("task", USER, "short"),
])
def test_invalid_approval_inputs_are_rejected(task_id, user_id, secret):
    with pytest.raises(ValueError):
        build_approval_payload(task_id, "task text", user_id, secret)
