"""Persistent Job lifecycle decisions for the overnight development worker.

The orchestrator owns retry policy; LangGraph owns the bounded node sequence.
Keeping this policy outside the graph prevents a long-running self-loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Optional


DEFAULT_JOB_MAX_SECONDS = int(os.environ.get("JOB_MAX_SECONDS", "21600"))


@dataclass(frozen=True)
class RetryDecision:
    retry_count: int
    retry: bool
    terminal_status: str
    reason: str


def decide_test_failure(job: dict) -> RetryDecision:
    """Consume one retry budget after a failed automated test."""
    retry_count = int(job.get("retry_count") or 0) + 1
    max_retries = max(0, int(job.get("max_retries") or 0))

    if retry_count <= max_retries:
        return RetryDecision(retry_count, True, "pending",
                             "automated test failed; retry through Debug -> Fix -> Patch -> Test")
    return RetryDecision(retry_count, False, "failed",
                         "automated test failed; retry limit reached")


def decide_executor_failure(job: dict) -> RetryDecision:
    """Consume one retry budget after an unexpected worker/executor error."""
    retry_count = int(job.get("retry_count") or 0) + 1
    max_retries = max(0, int(job.get("max_retries") or 0))
    if retry_count <= max_retries:
        return RetryDecision(retry_count, True, "pending", "worker execution failed; retry scheduled")
    return RetryDecision(retry_count, False, "failed", "worker execution failed; retry limit reached")


def _parse_timestamp(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def job_time_exceeded(job: dict, *, now: Optional[datetime] = None,
                      max_seconds: int = DEFAULT_JOB_MAX_SECONDS) -> bool:
    """Return True when a Job has exceeded its total wall-clock budget."""
    created = _parse_timestamp(job.get("created_at"))
    if created is None:
        return False
    current = now or datetime.now(timezone.utc)
    return (current - created).total_seconds() > max(0, int(max_seconds))


def _error_signature(value) -> Optional[str]:
    """Normalize volatile traceback details so identical failures can be detected."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("error") or value.get("message") or value.get("stderr") or value
    text = str(value).lower()
    text = re.sub(r"0x[0-9a-f]+", "0xADDR", text)
    text = re.sub(r"\b\d{3,}\b", "N", text)
    text = re.sub(r"/[^\s:'\"]+", "/PATH", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def test_failure_has_no_progress(previous_result, current_result) -> bool:
    """Detect an unchanged test failure after a Debug/Fix/Patch cycle."""
    def extract(value):
        if not value:
            return None
        if isinstance(value, dict):
            return value.get("test_result") or value.get("error") or value.get("message") or value
        try:
            parsed = json.loads(str(value))
            return parsed.get("test_result") or parsed.get("error") or parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            return value
    before = _error_signature(extract(previous_result))
    after = _error_signature(extract(current_result))
    return before is not None and before == after
