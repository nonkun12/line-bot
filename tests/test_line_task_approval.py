from datetime import datetime, timezone
import pytest
from core.line_task_approval import ApprovalCommand, parse_approval_command, validate_approval_request

def _candidate(**overrides):
    data = {
        "task_id": "review-gap-abc123", "issue_number": 123,
        "issue_state": "open", "candidate_label": True,
        "execution_approval_label": False, "execution_approved": False,
        "held": False, "resume_requires_review": False,
        "review_passed": True, "rea_passed": True, "base_sha": "a" * 40,
        "allowed_paths": ["tests/test_example.py"],
        "expires_at": "2026-11-20T23:59:00+00:00",
    }
    data.update(overrides)
    return data

def test_parse_only_explicit_task_approval_command():
    assert parse_approval_command("実行承認: review-gap-abc123") == ApprovalCommand("review-gap-abc123")
    assert parse_approval_command("承認 review-gap-abc123") is None
    assert parse_approval_command("実行承認:") is None
    assert parse_approval_command("実行承認: review-gap-abc123 extra") is None
    assert parse_approval_command("実行承認: 日本語ID") is None

def test_validate_approval_binds_identity_and_safety_snapshot():
    result = validate_approval_request(
        ApprovalCommand("review-gap-abc123"), user_id="U-authorized",
        allowed_user_ids={"U-authorized"}, candidate=_candidate(),
        now=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    assert result.task_id == "review-gap-abc123"
    assert result.issue_number == 123
    assert result.allowed_paths == ("tests/test_example.py",)
    assert result.approver_user_id == "U-authorized"

@pytest.mark.parametrize(("overrides", "message"), [
    ({"task_id": "other-task"}, "identity mismatch"),
    ({"issue_state": "closed"}, "not open"),
    ({"candidate_label": False}, "candidate label"),
    ({"execution_approved": True}, "already execution-approved"),
    ({"execution_approved": None}, "not explicitly false"),
    ({"held": True}, "held"), ({"held": None}, "held"),
    ({"resume_requires_review": True}, "requires review"),
    ({"review_passed": False}, "review has not passed"),
    ({"rea_passed": False}, "REA evidence"),
    ({"base_sha": "ABC"}, "base SHA"),
    ({"allowed_paths": ["scripts/unsafe.py"]}, "test-only path"),
    ({"allowed_paths": ["tests/test_a.py", "tests/test_b.py"]}, "test-only path"),
    ({"expires_at": "2020-01-01T00:00:00+00:00"}, "expired"),
    ({"expires_at": "2026-11-20T23:59:00"}, "timezone"),
])
def test_validate_approval_fails_closed(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_approval_request(
            ApprovalCommand("review-gap-abc123"), user_id="U-authorized",
            allowed_user_ids={"U-authorized"}, candidate=_candidate(**overrides),
            now=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))

def test_validate_approval_rejects_unauthorized_user():
    with pytest.raises(ValueError, match="unauthorized"):
        validate_approval_request(
            ApprovalCommand("review-gap-abc123"), user_id="U-stranger",
            allowed_user_ids={"U-authorized"}, candidate=_candidate(),
            now=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
