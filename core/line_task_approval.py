"""Fail-closed LINE adapter for one task-bound execution approval.

The preview command exposes the exact catalog instruction, paths, base SHA and
short expiry. Approval must echo the displayed instruction digest, base SHA,
and expiry. This module validates metadata only; dispatch and runtime gates
remain separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PREVIEW = re.compile(r"^承認候補[：:]\s*([a-z0-9][a-z0-9._-]{2,99})\s*$")
_APPROVAL = re.compile(
    r"^実行承認[：:]\s*([a-z0-9][a-z0-9._-]{2,99})\s+"
    r"([0-9a-f]{64})\s+([0-9a-f]{40})\s+(\d{10})\s*$"
)


@dataclass(frozen=True)
class ApprovalPreviewCommand:
    task_id: str


@dataclass(frozen=True)
class ApprovalCommand:
    task_id: str
    instruction_sha256: str
    base_sha: str
    expires_at: int


@dataclass(frozen=True)
class ApprovalDecision:
    task_id: str
    instruction_sha256: str
    allowed_paths_sha256: str
    base_sha: str
    expires_at: int
    approver_user_id: str


def parse_approval_preview_command(message: str) -> ApprovalPreviewCommand | None:
    if not isinstance(message, str):
        return None
    match = _PREVIEW.fullmatch(message.strip())
    if match is None:
        return None
    return ApprovalPreviewCommand(match.group(1))


def parse_approval_command(message: str) -> ApprovalCommand | None:
    """Accept only the exact copyable approval command returned by preview."""
    if not isinstance(message, str):
        return None
    match = _APPROVAL.fullmatch(message.strip())
    if match is None:
        return None
    task_id, instruction_sha256, base_sha, expires_at = match.groups()
    if not _TASK_ID.fullmatch(task_id):
        return None
    return ApprovalCommand(task_id, instruction_sha256, base_sha, int(expires_at))


def instruction_digest(instruction: str) -> str:
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


def allowed_paths_digest(paths: list[str]) -> str:
    canonical = sorted(paths)
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_approval_request(
    command: ApprovalCommand,
    *,
    user_id: str,
    allowed_user_ids: set[str],
    candidate: Mapping[str, Any],
    now: datetime | None = None,
) -> ApprovalDecision:
    """Validate a freshly fetched queue/catalog snapshot against the copied preview."""
    if not isinstance(command, ApprovalCommand):
        raise ValueError("explicit task-bound approval command required")
    if not user_id or user_id not in allowed_user_ids:
        raise ValueError("unauthorized LINE user")
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate snapshot is invalid")
    if candidate.get("task_id") != command.task_id:
        raise ValueError("task identity mismatch")
    if candidate.get("catalog_registered") is not True:
        raise ValueError("task is not registered in the trusted catalog")
    if candidate.get("catalog_match") is not True:
        raise ValueError("runtime task does not match the trusted catalog")
    if candidate.get("execution_approved") is not True:
        raise ValueError("catalog execution approval is missing")
    instruction = candidate.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("catalog instruction is missing")
    actual_instruction_digest = instruction_digest(instruction)
    if actual_instruction_digest != command.instruction_sha256:
        raise ValueError("instruction changed since preview")
    paths = candidate.get("allowed_paths")
    if (
        not isinstance(paths, list)
        or not paths
        or len(paths) > 10
        or not all(
            isinstance(path, str)
            and path
            and path == path.strip()
            and not path.startswith("/")
            and "\\" not in path
            and ".." not in path.split("/")
            for path in paths
        )
        or len(set(paths)) != len(paths)
    ):
        raise ValueError("catalog allowed paths are invalid")
    base_sha = candidate.get("base_sha")
    if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
        raise ValueError("candidate base SHA is invalid")
    if base_sha != command.base_sha:
        raise ValueError("repository HEAD changed since preview")
    expires_at = candidate.get("expires_at")
    if type(expires_at) is not int or expires_at != command.expires_at:
        raise ValueError("approval expiry does not match preview")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("current time must include timezone")
    remaining = expires_at - int(current.timestamp())
    if remaining <= 0:
        raise ValueError("approval preview expired")
    if remaining > 600:
        raise ValueError("approval preview expiry exceeds ten-minute limit")
    return ApprovalDecision(
        task_id=command.task_id,
        instruction_sha256=actual_instruction_digest,
        allowed_paths_sha256=allowed_paths_digest(paths),
        base_sha=base_sha,
        expires_at=expires_at,
        approver_user_id=user_id,
    )
