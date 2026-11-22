"""One-time, task-bound LINE approval challenges.

A preview challenge is server-issued, signed, short-lived, and carries a stable
nonce. Replaying the exact approval command therefore reuses the same nonce;
the guarded runtime's atomic Git-ref ledger rejects every replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Any, Mapping

_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PREVIEW = re.compile(r"^承認候補[：:]\s*([a-z0-9][a-z0-9._-]{2,99})\s*$")
_APPROVAL = re.compile(
    r"^実行承認[：:]\s*([a-z0-9][a-z0-9._-]{2,99})\s+"
    r"([0-9a-f]{64})\s+([0-9a-f]{40})\s+(\d{10})\s+"
    r"([0-9a-f]{32})\s+([0-9a-f]{64})\s*$"
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
    nonce: str
    challenge_signature: str


@dataclass(frozen=True)
class ApprovalDecision:
    task_id: str
    instruction_sha256: str
    allowed_paths_sha256: str
    base_sha: str
    expires_at: int
    approver_user_id: str
    nonce: str


def _secret_ok(secret: str) -> bool:
    return isinstance(secret, str) and len(secret.encode("utf-8")) >= 32


def instruction_digest(instruction: str) -> str:
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


def allowed_paths_digest(paths: list[str]) -> str:
    canonical = sorted(paths)
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _challenge_payload(
    *, task_id: str, instruction_sha256: str, allowed_paths_sha256: str,
    base_sha: str, expires_at: int, approver_user_id: str, nonce: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "instruction_sha256": instruction_sha256,
        "allowed_paths_sha256": allowed_paths_sha256,
        "base_sha": base_sha,
        "expires_at": expires_at,
        "approver_user_id": approver_user_id,
        "nonce": nonce,
    }


def sign_preview_challenge(
    *, task_id: str, instruction_sha256: str, allowed_paths_sha256: str,
    base_sha: str, expires_at: int, approver_user_id: str, nonce: str, secret: str,
) -> str:
    if not _secret_ok(secret):
        raise ValueError("LINE approval signing secret is missing or too short")
    if not _TASK_ID.fullmatch(task_id) or not _HEX64.fullmatch(instruction_sha256):
        raise ValueError("approval task or instruction digest is invalid")
    if not _SHA.fullmatch(base_sha) or not _HEX64.fullmatch(allowed_paths_sha256):
        raise ValueError("approval base or paths digest is invalid")
    if type(expires_at) is not int or not approver_user_id or not _HEX32.fullmatch(nonce):
        raise ValueError("approval challenge fields are invalid")
    payload = _challenge_payload(
        task_id=task_id, instruction_sha256=instruction_sha256,
        allowed_paths_sha256=allowed_paths_sha256, base_sha=base_sha,
        expires_at=expires_at, approver_user_id=approver_user_id, nonce=nonce,
    )
    payload["purpose"] = "line-task-approval-preview-v1"
    return hmac.new(secret.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def verify_preview_challenge(command: ApprovalCommand, *, approver_user_id: str,
                             allowed_paths_sha256: str, secret: str) -> bool:
    if not _secret_ok(secret):
        return False
    try:
        expected = sign_preview_challenge(
            task_id=command.task_id,
            instruction_sha256=command.instruction_sha256,
            allowed_paths_sha256=allowed_paths_sha256,
            base_sha=command.base_sha,
            expires_at=command.expires_at,
            approver_user_id=approver_user_id,
            nonce=command.nonce,
            secret=secret,
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, command.challenge_signature)


def parse_approval_preview_command(message: str) -> ApprovalPreviewCommand | None:
    if not isinstance(message, str):
        return None
    match = _PREVIEW.fullmatch(message.strip())
    return ApprovalPreviewCommand(match.group(1)) if match else None


def parse_approval_command(message: str) -> ApprovalCommand | None:
    if not isinstance(message, str):
        return None
    match = _APPROVAL.fullmatch(message.strip())
    if not match:
        return None
    task_id, digest, base_sha, expiry, nonce, signature = match.groups()
    if not _TASK_ID.fullmatch(task_id):
        return None
    return ApprovalCommand(task_id, digest, base_sha, int(expiry), nonce, signature)


def sign_approval_envelope(decision: ApprovalDecision, *, secret: str) -> str:
    if not _secret_ok(secret):
        raise ValueError("LINE approval signing secret is missing or too short")
    payload = _challenge_payload(
        task_id=decision.task_id,
        instruction_sha256=decision.instruction_sha256,
        allowed_paths_sha256=decision.allowed_paths_sha256,
        base_sha=decision.base_sha,
        expires_at=decision.expires_at,
        approver_user_id=decision.approver_user_id,
        nonce=decision.nonce,
    )
    payload["purpose"] = "line-task-approval-execution-v1"
    return hmac.new(secret.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def verify_approval_envelope_signature(
    *, task_id: str, instruction_sha256: str, allowed_paths_sha256: str,
    base_sha: str, expires_at: int, approver_user_id: str, nonce: str,
    signature: str, secret: str,
) -> bool:
    if not _secret_ok(secret) or not isinstance(signature, str) or not _HEX64.fullmatch(signature):
        return False
    try:
        decision = ApprovalDecision(
            task_id, instruction_sha256, allowed_paths_sha256, base_sha,
            expires_at, approver_user_id, nonce,
        )
        expected = sign_approval_envelope(decision, secret=secret)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, signature)


def validate_approval_request(
    command: ApprovalCommand, *, user_id: str, allowed_user_ids: set[str],
    candidate: Mapping[str, Any], now_epoch: int, secret: str,
) -> ApprovalDecision:
    if not isinstance(command, ApprovalCommand):
        raise ValueError("explicit task-bound approval command required")
    if not user_id or user_id not in allowed_user_ids:
        raise ValueError("unauthorized LINE user")
    if not isinstance(candidate, Mapping) or candidate.get("task_id") != command.task_id:
        raise ValueError("task identity mismatch")
    if candidate.get("catalog_registered") is not True or candidate.get("catalog_match") is not True:
        raise ValueError("task is not an exact trusted catalog candidate")
    if candidate.get("execution_approved") is not True:
        raise ValueError("catalog execution approval is missing")
    if candidate.get("task_held") is True:
        raise ValueError("task is currently held and requires human review")
    instruction = candidate.get("instruction")
    paths = candidate.get("allowed_paths")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("catalog instruction is missing")
    if (
        not isinstance(paths, list) or not paths or len(paths) > 10
        or not all(isinstance(p, str) and p and p == p.strip()
                   and not p.startswith("/") and "\\" not in p
                   and ".." not in p.split("/") for p in paths)
        or len(set(paths)) != len(paths)
    ):
        raise ValueError("catalog allowed paths are invalid")
    digest = instruction_digest(instruction)
    paths_digest = allowed_paths_digest(paths)
    if digest != command.instruction_sha256:
        raise ValueError("instruction changed since preview")
    if candidate.get("base_sha") != command.base_sha or not _SHA.fullmatch(command.base_sha):
        raise ValueError("repository HEAD changed since preview")
    remaining = command.expires_at - int(now_epoch)
    if remaining <= 0 or remaining > 300:
        raise ValueError("approval challenge expired or exceeds five-minute limit")
    if not verify_preview_challenge(
        command, approver_user_id=user_id,
        allowed_paths_sha256=paths_digest, secret=secret,
    ):
        raise ValueError("approval challenge signature invalid")
    return ApprovalDecision(
        command.task_id, digest, paths_digest, command.base_sha,
        command.expires_at, user_id, command.nonce,
    )
