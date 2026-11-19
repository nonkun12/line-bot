"""Queue explicit LINE requests for the Mac-local OpenClaw agent."""
from __future__ import annotations

import os

from db import create_job

OPENCLAW_JOB_TYPE = "openclaw"
MAX_OPENCLAW_MESSAGE_CHARS = 4000


class OpenClawBridgeError(ValueError):
    """A request cannot safely be queued for the local OpenClaw worker."""


def is_openclaw_intent(message: str) -> bool:
    """Require a deliberate prefix; ordinary chat never reaches local execution."""
    if not isinstance(message, str):
        return False
    normalized = message.strip()
    return normalized.lower().startswith(("openclaw:", "openclaw ")) or normalized.startswith("OpenClawで")


def normalize_openclaw_message(message: str) -> str:
    if not isinstance(message, str):
        raise OpenClawBridgeError("message is required")
    normalized = message.strip()
    if normalized.lower().startswith("openclaw:"):
        normalized = normalized[len("openclaw:"):].strip()
    elif normalized.lower().startswith("openclaw "):
        normalized = normalized[len("openclaw "):].strip()
    elif normalized.startswith("OpenClawで"):
        normalized = normalized[len("OpenClawで"):].strip()
    if not normalized:
        raise OpenClawBridgeError("OpenClaw task is required")
    if len(normalized) > MAX_OPENCLAW_MESSAGE_CHARS:
        raise OpenClawBridgeError("OpenClaw task exceeds 4000 characters")
    return normalized


def enqueue_openclaw_request(user_id: str, message: str) -> int:
    user = str(user_id or "").strip()
    if not user or len(user) > 200:
        raise OpenClawBridgeError("valid user_id is required")
    if not is_openclaw_intent(message):
        raise OpenClawBridgeError("explicit OpenClaw prefix is required")
    task = normalize_openclaw_message(message)
    bridge_key = os.environ.get("OPENCLAW_BRIDGE_KEY", "").strip()
    if len(bridge_key) < 24:
        raise OpenClawBridgeError("OpenClaw Mac bridge key must be at least 24 characters")
    job_id = create_job(user, task, job_type=OPENCLAW_JOB_TYPE, source="line", max_retries=3)
    if not isinstance(job_id, int) or job_id <= 0:
        raise OpenClawBridgeError("failed to create OpenClaw job")
    return job_id
