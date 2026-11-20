"Fail-closed LINE command adapter for autonomous task execution approval.

Parses an explicit command and validates a separately resolved trusted snapshot.
It does not fetch GitHub data, mutate state, grant approval, or dispatch.
"
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping

_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_COMMAND = re.compile(r"^実行承認[：:][ ]*([a-z0-9][a-z0-9._-]{2,99})[ ]*$")

@dataclass(frozen=True)
class ApprovalCommand:
    task_id: str

@dataclass(frozen=True)
class ApprovalDecision:
    task_id: str
    issue_number: int
    base_sha: str
    allowed_paths: tuple[str, ...]
    approver_user_id: str

def parse_approval_command(message: str) -> ApprovalCommand | None:
    if not isinstance(message, str):
        return None
    match = _COMMAND.fullmatch(message.strip())
    if match is None:
        return None
    task_id = match.group(1)
    if not _TASK_ID.fullmatch(task_id):
        return None
    return ApprovalCommand(task_id=task_id)

def validate_approval_request(command: ApprovalCommand, *, user_id: str,
        allowed_user_ids: set[str], candidate: Mapping[str, Any],
        now: datetime | None = None) -> ApprovalDecision:
    if not isinstance(command, ApprovalCommand):
        raise ValueError("explicit approval command required")
    if not user_id or user_id not in allowed_user_ids:
        raise ValueError("unauthorized LINE user")
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate snapshot is invalid")
    if candidate.get("task_id") != command.task_id:
        raise ValueError("task identity mismatch")
    issue_number = candidate.get("issue_number")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("candidate issue number is invalid")
    if candidate.get("issue_state") != "open":
        raise ValueError("candidate issue is not open")
    if candidate.get("candidate_label") is not True:
        raise ValueError("candidate label is missing")
    if candidate.get("execution_approval_label") is True:
        raise ValueError("task is already execution-approved")
    if candidate.get("execution_approved") is not False:
        raise ValueError("execution approval state is not explicitly false")
    if candidate.get("held") is not False:
        raise ValueError("task is held or hold state is unknown")
    if candidate.get("resume_requires_review") is not False:
        raise ValueError("task requires review or review state is unknown")
    if candidate.get("review_passed") is not True:
        raise ValueError("independent review has not passed")
    if candidate.get("rea_passed") is not True:
        raise ValueError("REA evidence has not passed")
    base_sha = candidate.get("base_sha")
    if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
        raise ValueError("candidate base SHA is invalid")
    paths = candidate.get("allowed_paths")
    if (not isinstance(paths, list) or len(paths) != 1
            or not isinstance(paths[0], str)
            or not re.fullmatch(r"tests/test_[A-Za-z0-9_]+[.]py", paths[0])):
        raise ValueError("exactly one test-only path must be allowlisted")
    expires_at = candidate.get("expires_at")
    if not isinstance(expires_at, str):
        raise ValueError("approval request expiry is missing")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("approval request expiry is invalid") from exc
    if expiry.tzinfo is None:
        raise ValueError("approval request expiry must include timezone")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("current time must include timezone")
    if expiry <= current:
        raise ValueError("approval request expired")
    return ApprovalDecision(command.task_id, issue_number, base_sha,
                            (paths[0],), user_id)
