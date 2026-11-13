"""Independent, free-only anti-runaway guard for Orca execution.

The run_guard record is part of the durable queue snapshot and is advanced in
the same CAS write as the single-task claim. No paid service or auto-retry is
permitted. Missing or unverifiable guard state blocks execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_TASKS_PER_RUN = 1
MAX_RUN_SECONDS = 1800
MAX_ATTEMPTS_PER_TASK_PER_RUN = 1
MAX_CONSECUTIVE_FAILURES = 2
MIN_COOLDOWN_SECONDS = 3600


class RunawayGuardRejected(ValueError):
    pass


def _parse(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RunawayGuardRejected(f"{field}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RunawayGuardRejected(f"{field}_invalid")
    if parsed.tzinfo is None:
        raise RunawayGuardRejected(f"{field}_timezone_missing")
    return parsed.astimezone(timezone.utc)


def validate_and_consume_claim(*, state: dict[str, Any], task_id: str,
                               now: datetime) -> dict[str, Any]:
    """Validate durable run limits and return a copied guard with one slot consumed."""
    guard = state.get("run_guard")
    if not isinstance(guard, dict):
        raise RunawayGuardRejected("durable_run_guard_missing")
    required = {
        "run_id", "started_at", "tasks_claimed", "attempts_by_task",
        "consecutive_failures", "circuit_breaker_until",
        "paid_services_enabled", "automatic_retry_enabled",
    }
    if set(guard) != required:
        raise RunawayGuardRejected("durable_run_guard_schema_invalid")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise RunawayGuardRejected("guard_clock_timezone_missing")
    if not isinstance(guard["run_id"], str) or not guard["run_id"]:
        raise RunawayGuardRejected("guard_run_id_invalid")
    started = _parse(guard["started_at"], "guard_started_at")
    current = now.astimezone(timezone.utc)
    if current < started:
        raise RunawayGuardRejected("guard_clock_before_run_start")
    if (current - started).total_seconds() > MAX_RUN_SECONDS:
        raise RunawayGuardRejected("run_time_limit_exceeded")
    if isinstance(guard["tasks_claimed"], bool) or not isinstance(guard["tasks_claimed"], int):
        raise RunawayGuardRejected("tasks_claimed_invalid")
    if guard["tasks_claimed"] >= MAX_TASKS_PER_RUN:
        raise RunawayGuardRejected("max_tasks_per_run_exceeded")
    if guard["tasks_claimed"] < 0:
        raise RunawayGuardRejected("tasks_claimed_invalid")
    attempts = guard["attempts_by_task"]
    if not isinstance(attempts, dict):
        raise RunawayGuardRejected("attempt_ledger_invalid")
    count = attempts.get(task_id, 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise RunawayGuardRejected("attempt_count_invalid")
    if count >= MAX_ATTEMPTS_PER_TASK_PER_RUN:
        raise RunawayGuardRejected("max_attempts_per_task_exceeded")
    failures = guard["consecutive_failures"]
    if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
        raise RunawayGuardRejected("failure_counter_invalid")
    if failures >= MAX_CONSECUTIVE_FAILURES:
        raise RunawayGuardRejected("failure_circuit_breaker_open")
    breaker = guard["circuit_breaker_until"]
    if breaker is not None and current < _parse(breaker, "circuit_breaker_until"):
        raise RunawayGuardRejected("circuit_breaker_cooldown_active")
    if guard["paid_services_enabled"] is not False:
        raise RunawayGuardRejected("paid_services_forbidden")
    if guard["automatic_retry_enabled"] is not False:
        raise RunawayGuardRejected("automatic_retry_forbidden")

    updated = dict(guard)
    updated_attempts = dict(attempts)
    updated_attempts[task_id] = count + 1
    updated["attempts_by_task"] = updated_attempts
    updated["tasks_claimed"] += 1
    return updated


def validate_worker_start(*, state: dict[str, Any], task_id: str,
                          run_id: str, now: datetime) -> None:
    """Re-check independent limits at worker boundary; never consumes a slot."""
    guard = state.get("run_guard")
    if not isinstance(guard, dict):
        raise RunawayGuardRejected("durable_run_guard_missing")
    if guard.get("run_id") != run_id:
        raise RunawayGuardRejected("guard_run_id_mismatch")
    if guard.get("tasks_claimed") != 1:
        raise RunawayGuardRejected("worker_run_task_count_invalid")
    attempts = guard.get("attempts_by_task")
    if not isinstance(attempts, dict) or attempts.get(task_id) != 1:
        raise RunawayGuardRejected("worker_attempt_count_invalid")
    if guard.get("paid_services_enabled") is not False:
        raise RunawayGuardRejected("paid_services_forbidden")
    if guard.get("automatic_retry_enabled") is not False:
        raise RunawayGuardRejected("automatic_retry_forbidden")
    if guard.get("consecutive_failures", MAX_CONSECUTIVE_FAILURES) >= MAX_CONSECUTIVE_FAILURES:
        raise RunawayGuardRejected("failure_circuit_breaker_open")
    started = _parse(guard.get("started_at"), "guard_started_at")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise RunawayGuardRejected("guard_clock_timezone_missing")
    current = now.astimezone(timezone.utc)
    if current < started or (current - started).total_seconds() > MAX_RUN_SECONDS:
        raise RunawayGuardRejected("run_time_limit_exceeded")
    breaker = guard.get("circuit_breaker_until")
    if breaker is not None and current < _parse(breaker, "circuit_breaker_until"):
        raise RunawayGuardRejected("circuit_breaker_cooldown_active")
