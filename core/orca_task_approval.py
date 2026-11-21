"""Task-bound HMAC approval payloads for explicit LINE approvals."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

_LINE_USER_ID_RE = re.compile(r"^U[0-9a-fA-F]{32}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def is_valid_line_user_id(user_id: str | None) -> bool:
    return isinstance(user_id, str) and _LINE_USER_ID_RE.fullmatch(user_id) is not None


def build_approval_payload(
    task_id: str,
    request_text: str,
    user_id: str,
    secret: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ValueError("invalid task id")
    if not _LINE_USER_ID_RE.fullmatch(user_id):
        raise ValueError("invalid LINE user id")
    if not secret or len(secret.encode("utf-8")) < 32:
        raise ValueError("approval HMAC secret is not configured securely")
    issued = now or datetime.now(timezone.utc)
    if issued.tzinfo is None:
        raise ValueError("approval timestamp must be timezone-aware")
    issued = issued.astimezone(timezone.utc).replace(microsecond=0)
    expires = issued + timedelta(hours=1)
    issued_at = issued.isoformat().replace("+00:00", "Z")
    expires_at = expires.isoformat().replace("+00:00", "Z")
    request_hash = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
    canonical = "\n".join(
        ("v1", task_id, request_hash, user_id, issued_at, expires_at)
    )
    nonce = secrets.token_urlsafe(24)
    canonical = "\n".join((canonical, nonce))
    signature = hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "approver_user_id": user_id,
        "request_hash": request_hash,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signature": signature,
        "nonce": nonce,
    }
