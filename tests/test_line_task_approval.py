from datetime import datetime, timezone

import pytest

from core.line_task_approval import (
    ApprovalCommand,
    ApprovalPreviewCommand,
    ApprovalDecision,
    allowed_paths_digest,
    instruction_digest,
    parse_approval_command,
    parse_approval_preview_command,
    sign_approval_envelope,
    verify_approval_envelope_signature,
    validate_approval_request,
)


def _candidate(**overrides):
    data = {
        "task_id": "review-gap-abc123",
        "catalog_registered": True,
        "catalog_match": True,
        "execution_approved": True,
        "instruction": "Add one bounded regression test.",
        "allowed_paths": ["tests/test_example.py"],
        "base_sha": "a" * 40,
        "expires_at": 1795212000,
    }
    data.update(overrides)
    return data


def _command(candidate=None):
    value = candidate or _candidate()
    return ApprovalCommand(
        task_id=value["task_id"],
        instruction_sha256=instruction_digest(value["instruction"]),
        base_sha=value["base_sha"],
        expires_at=value["expires_at"],
    )



def test_signed_envelope_binds_approver_expiry_and_nonce():
    secret = "test-only-shared-approval-secret-32-bytes"
    decision = ApprovalDecision(
        task_id="approved-task",
        instruction_sha256="a" * 64,
        allowed_paths_sha256="b" * 64,
        base_sha="c" * 40,
        expires_at=1_900_000_000,
        approver_user_id="U-authorized-user",
    )
    nonce = "d" * 32
    signature = sign_approval_envelope(decision, nonce=nonce, secret=secret)
    common = {
        "task_id": decision.task_id,
        "instruction_sha256": decision.instruction_sha256,
        "allowed_paths_sha256": decision.allowed_paths_sha256,
        "base_sha": decision.base_sha,
        "expires_at": decision.expires_at,
        "approver_user_id": decision.approver_user_id,
        "nonce": nonce,
        "signature": signature,
        "secret": secret,
    }
    assert verify_approval_envelope_signature(**common)
    assert not verify_approval_envelope_signature(**{**common, "approver_user_id": "U-forged"})
    assert not verify_approval_envelope_signature(**{**common, "expires_at": decision.expires_at + 1})
    assert not verify_approval_envelope_signature(**{**common, "nonce": "e" * 32})
    assert not verify_approval_envelope_signature(**{**common, "secret": ""})


def test_signing_rejects_missing_or_weak_secret():
    decision = ApprovalDecision("approved-task", "a" * 64, "b" * 64, "c" * 40, 1_900_000_000, "U-user")
    with pytest.raises(ValueError):
        sign_approval_envelope(decision, nonce="d" * 32, secret="")
    with pytest.raises(ValueError):
        sign_approval_envelope(decision, nonce="invalid", secret="x" * 40)

def test_parse_preview_and_exact_task_bound_approval_commands():
    assert parse_approval_preview_command("承認候補: review-gap-abc123") == ApprovalPreviewCommand(
        "review-gap-abc123"
    )
    command = "実行承認: review-gap-abc123 " + "b" * 64 + " " + "a" * 40 + " 1795212000"
    assert parse_approval_command(command) == ApprovalCommand(
        "review-gap-abc123", "b" * 64, "a" * 40, 1795212000
    )
    assert parse_approval_command("実行承認: review-gap-abc123") is None
    assert parse_approval_command(command + " extra") is None
    assert parse_approval_preview_command("承認候補:") is None


def test_validate_approval_binds_catalog_task_and_preview_snapshot():
    result = validate_approval_request(
        _command(),
        user_id="U-authorized",
        allowed_user_ids={"U-authorized"},
        candidate=_candidate(),
        now=datetime.fromtimestamp(1795211700, timezone.utc),
    )
    assert result.task_id == "review-gap-abc123"
    assert result.instruction_sha256 == instruction_digest("Add one bounded regression test.")
    assert result.allowed_paths_sha256 == allowed_paths_digest(["tests/test_example.py"])
    assert result.base_sha == "a" * 40
    assert result.approver_user_id == "U-authorized"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"task_id": "other-task"}, "identity mismatch"),
        ({"catalog_registered": False}, "trusted catalog"),
        ({"catalog_match": False}, "trusted catalog"),
        ({"execution_approved": False}, "catalog execution approval"),
        ({"instruction": "changed"}, "instruction changed"),
        ({"allowed_paths": []}, "allowed paths"),
        ({"allowed_paths": ["../unsafe.py"]}, "allowed paths"),
        ({"allowed_paths": ["/absolute.py"]}, "allowed paths"),
        ({"allowed_paths": ["tests/a.py", "tests/a.py"]}, "allowed paths"),
        ({"base_sha": "ABC"}, "base SHA"),
        ({"base_sha": "c" * 40}, "HEAD changed"),
        ({"expires_at": 1795212001}, "expiry does not match"),
        ({"expires_at": 1795210000}, "expiry does not match"),
    ],
)
def test_validation_fails_closed_for_snapshot_mismatch(overrides, message):
    candidate = _candidate(**overrides)
    with pytest.raises(ValueError, match=message):
        validate_approval_request(
            _command(),
            user_id="U-authorized",
            allowed_user_ids={"U-authorized"},
            candidate=candidate,
            now=datetime.fromtimestamp(1795211700, timezone.utc),
        )


def test_validation_rejects_expired_or_overlong_preview():
    with pytest.raises(ValueError, match="expired"):
        validate_approval_request(
            _command(),
            user_id="U-authorized",
            allowed_user_ids={"U-authorized"},
            candidate=_candidate(),
            now=datetime.fromtimestamp(1795212000, timezone.utc),
        )
    candidate = _candidate(expires_at=1795212601)
    command = _command(candidate)
    with pytest.raises(ValueError, match="ten-minute"):
        validate_approval_request(
            command,
            user_id="U-authorized",
            allowed_user_ids={"U-authorized"},
            candidate=candidate,
            now=datetime.fromtimestamp(1795211700, timezone.utc),
        )


def test_validation_rejects_unauthorized_user():
    with pytest.raises(ValueError, match="unauthorized"):
        validate_approval_request(
            _command(),
            user_id="U-stranger",
            allowed_user_ids={"U-authorized"},
            candidate=_candidate(),
            now=datetime.fromtimestamp(1795211700, timezone.utc),
        )
