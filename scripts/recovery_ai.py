"""Deterministic, fail-closed recovery controller for the autonomous loop.

This module intentionally does not call an LLM, run shell commands, apply patches,
merge, or deploy. It records sanitized incident metadata and returns a bounded
recovery decision for a separately guarded caller to enforce.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1
HOLD_AFTER_FAILURES = 3
MAX_TRANSIENT_RETRIES = 2
MAX_REPAIR_ATTEMPTS_PER_FINGERPRINT = 1

TRANSIENT_CATEGORIES = frozenset({"network_transient", "service_unavailable", "rate_limited"})
# Unknown runtime failures get one bounded retry; the second identical failure holds.
REPAIRABLE_CATEGORIES = frozenset({"test_regression", "timeout", "process_crash", "unknown"})
NON_REPAIRABLE_CATEGORIES = frozenset({"invalid_task", "invalid_evidence", "security_violation"})
FAILURE_CATEGORIES = (
    TRANSIENT_CATEGORIES | REPAIRABLE_CATEGORIES | NON_REPAIRABLE_CATEGORIES
    | {"state_persistence_failure", "unknown"}
)


class RecoveryStateError(RuntimeError):
    """Raised when recovery state cannot be trusted or durably persisted."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 100 or not all(c.isalnum() or c in "._-" for c in value):
        raise ValueError("invalid task ID")
    return value


def _normalized_tests(failing_tests: Iterable[str]) -> list[str]:
    values = []
    for item in failing_tests:
        # Store identifiers only; never store test output, prompts, tokens, or exception text.
        text = str(item).strip().replace("\\", "/")
        if not text or len(text) > 240 or any(ord(c) < 32 for c in text):
            raise ValueError("invalid failing test identifier")
        values.append(text)
    return sorted(set(values))[:100]


def failure_fingerprint(task_id: str, category: str, failing_tests: Iterable[str] = ()) -> str:
    task_id = _safe_id(task_id)
    if category not in FAILURE_CATEGORIES:
        category = "unknown"
    payload = json.dumps(
        {"task_id": task_id, "category": category, "failing_tests": _normalized_tests(failing_tests)},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    task_id: str
    fingerprint: str
    consecutive_failures: int
    retry_after_seconds: int = 0
    requires_human: bool = False


class RecoveryStore:
    """Small JSON state store with atomic replacement and fail-closed reads/writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "tasks": {}, "checkpoint": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecoveryStateError("recovery state unreadable") from exc
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise RecoveryStateError("recovery state schema invalid")
        if not isinstance(data.get("tasks"), dict):
            raise RecoveryStateError("recovery task state invalid")
        if "checkpoint" not in data:
            raise RecoveryStateError("recovery checkpoint field missing")
        return data

    def _write(self, data: dict) -> None:
        parent = self.path.parent
        temp_name = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=parent, delete=False) as handle:
                temp_name = handle.name
                json.dump(data, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            temp_name = None
            # Make the rename durable where supported.
            dir_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError as exc:
            raise RecoveryStateError("recovery state persistence failed") from exc
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    def record_preflight_blocked(
        self, task_id: str, reason_code: str, prerequisite_id: str | None = None
    ) -> dict:
        """Persist a preflight block separately, without counting a task failure.

        This is evidence of a gate decision, not permission to retry or resume.
        Repeated identical events are deduplicated and counted, with bounded history.
        """
        task_id = _safe_id(task_id)
        if not isinstance(reason_code, str) or not re.fullmatch(
            r"(?:control_tower_gate|control_tower_rea):[A-Za-z0-9._-]{1,80}|control_tower_head_changed",
            reason_code,
        ):
            raise ValueError("invalid preflight blocked reason code")
        if prerequisite_id is not None:
            prerequisite_id = _safe_id(prerequisite_id)
        identity = {
            "task_id": task_id,
            "reason_code": reason_code,
            "prerequisite_id": prerequisite_id,
        }
        fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        data = self._read()
        events = data.setdefault("preflight_blocked", {})
        if not isinstance(events, dict):
            raise RecoveryStateError("preflight blocked event state invalid")
        previous = events.get(fingerprint)
        if previous is not None and not isinstance(previous, dict):
            raise RecoveryStateError("preflight blocked event record invalid")
        now = utc_now()
        occurrences = int(previous.get("occurrences", 0)) + 1 if previous else 1
        events[fingerprint] = {
            **identity,
            "fingerprint": fingerprint,
            "status": "PENDING_PREREQUISITE_OR_REVIEW",
            "first_seen_at": previous.get("first_seen_at", now) if previous else now,
            "last_seen_at": now,
            "occurrences": occurrences,
        }
        # Keep the newest 200 unique incidents; never discard task failure history.
        if len(events) > 200:
            ordered = sorted(
                events.items(), key=lambda item: str(item[1].get("last_seen_at", ""))
            )
            data["preflight_blocked"] = dict(ordered[-200:])
        self._write(data)
        return dict(data["preflight_blocked"][fingerprint])

    def record_failure(
        self, task_id: str, category: str, failing_tests: Iterable[str] = (),
        *, transient_attempt: int = 1,
    ) -> RecoveryDecision:
        task_id = _safe_id(task_id)
        if category not in FAILURE_CATEGORIES:
            category = "unknown"
        tests = _normalized_tests(failing_tests)
        fingerprint = failure_fingerprint(task_id, category, tests)
        data = self._read()
        previous = data["tasks"].get(task_id, {})
        if not isinstance(previous, dict):
            raise RecoveryStateError("task recovery record invalid")
        count = int(previous.get("consecutive_failures", 0)) + 1
        history = previous.get("fingerprints", [])
        if not isinstance(history, list) or not all(isinstance(x, str) for x in history):
            raise RecoveryStateError("failure fingerprint history invalid")
        same_count = sum(1 for item in history if item == fingerprint)
        now = utc_now()
        was_held = previous.get("held") is True
        data["tasks"][task_id] = {
            "consecutive_failures": count,
            "last_category": category,
            "last_fingerprint": fingerprint,
            "fingerprints": (history + [fingerprint])[-20:],
            "same_fingerprint_attempts": same_count + 1,
            "held": was_held,
            "updated_at": now,
        }
        record = data["tasks"][task_id]
        # Preserve review metadata across a failure after an explicitly approved
        # resume; a subsequent failure must not erase the human-review barrier.
        for key in ("resume_requires_review", "resumed_at", "last_success_at", "last_success_evidence"):
            if key in previous:
                record[key] = previous[key]
        if category == "state_persistence_failure":
            action, reason, delay, human = "STOP_FAIL_CLOSED", "state_persistence_failure", 0, True
        elif was_held:
            # Preserve the original hold cause. Legacy state files did not store it,
            # so report that limitation rather than inventing a historical reason.
            record["hold_reason"] = previous.get("hold_reason") or "legacy_hold_reason_unavailable"
            record["hold_category"] = (
                previous.get("hold_category")
                or "legacy_hold_category_unavailable"
            )
            action, reason, delay, human = "HOLD", "previous_hold_requires_explicit_resume", 0, True
        elif count >= HOLD_AFTER_FAILURES or category in NON_REPAIRABLE_CATEGORIES:
            record["held"] = True
            action, reason, delay, human = "HOLD", (
                "failure_threshold_reached" if count >= HOLD_AFTER_FAILURES
                else "non_repairable_failure"
            ), 0, True
            record["hold_reason"] = reason
            record["hold_category"] = category
        elif category in TRANSIENT_CATEGORIES and transient_attempt <= MAX_TRANSIENT_RETRIES:
            action, reason, delay, human = "RETRY", "bounded_transient_retry", min(30 * (2 ** (transient_attempt - 1)), 120), False
        elif category in REPAIRABLE_CATEGORIES and same_count < MAX_REPAIR_ATTEMPTS_PER_FINGERPRINT:
            action, reason, delay, human = "REPAIR_ONCE", "bounded_repair_attempt", 0, False
        else:
            record["held"] = True
            action, reason, delay, human = "HOLD", "repair_budget_exhausted", 0, True
            record["hold_reason"] = reason
            record["hold_category"] = category
        record["last_decision_action"] = action
        record["last_decision_reason"] = reason
        self._write(data)
        return RecoveryDecision(action, reason, task_id, fingerprint, count, delay, human)

    def record_success(
        self, task_id: str, *, verified: bool, evidence: dict | None = None
    ) -> None:
        """Persist verified success and its exact per-run identity atomically."""
        task_id = _safe_id(task_id)
        if verified is not True:
            raise ValueError("only verified success may reset failure counters")
        if not isinstance(evidence, dict) or set(evidence) != {
            "task_id", "base_sha", "produced_sha", "run_nonce"
        }:
            raise ValueError("verified success evidence missing or invalid")
        if evidence.get("task_id") != task_id:
            raise ValueError("verified success task identity mismatch")
        if not isinstance(evidence.get("base_sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", evidence["base_sha"]):
            raise ValueError("verified success base SHA invalid")
        if not isinstance(evidence.get("produced_sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", evidence["produced_sha"]):
            raise ValueError("verified success produced SHA invalid")
        if not isinstance(evidence.get("run_nonce"), str) or not re.fullmatch(r"[0-9a-f]{32}", evidence["run_nonce"]):
            raise ValueError("verified success nonce invalid")
        data = self._read()
        record = data["tasks"].get(task_id)
        if record is None:
            record = {"consecutive_failures": 0, "same_fingerprint_attempts": 0, "held": False}
            data["tasks"][task_id] = record
        if not isinstance(record, dict):
            raise RecoveryStateError("task recovery record invalid")
        if record.get("held") is True:
            raise ValueError("held task requires explicit resume before success can reset state")
        record["consecutive_failures"] = 0
        record["same_fingerprint_attempts"] = 0
        record["last_success_at"] = utc_now()
        record["last_success_evidence"] = dict(evidence)
        self._write(data)

    def save_checkpoint(self, task_id: str, checkpoint_id: str, *, verified: bool) -> None:
        task_id = _safe_id(task_id)
        checkpoint_id = _safe_id(checkpoint_id)
        if verified is not True:
            raise ValueError("only a verified checkpoint can be saved")
        data = self._read()
        data["checkpoint"] = {
            "task_id": task_id, "checkpoint_id": checkpoint_id,
            "verified": True, "saved_at": utc_now(),
        }
        self._write(data)

    def resumable_checkpoint(self) -> dict | None:
        checkpoint = self._read().get("checkpoint")
        if checkpoint is None:
            return None
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("verified") is not True
            or not isinstance(checkpoint.get("task_id"), str)
            or not isinstance(checkpoint.get("checkpoint_id"), str)
        ):
            raise RecoveryStateError("checkpoint is not verified")
        return dict(checkpoint)

    def resume_held_task(self, task_id: str, *, cause_fixed: bool) -> None:
        task_id = _safe_id(task_id)
        if cause_fixed is not True:
            raise ValueError("explicit confirmation that the cause is fixed is required")
        data = self._read()
        record = data["tasks"].get(task_id)
        if not isinstance(record, dict) or record.get("held") is not True:
            raise ValueError("task is not held")
        record["held"] = False
        record["consecutive_failures"] = 0
        record["resumed_at"] = utc_now()
        record["resume_requires_review"] = True
        self._write(data)

    def confirm_resume_review(self, task_id: str, *, reviewed: bool) -> None:
        """Acknowledge the required post-resume review before a held task can run."""
        task_id = _safe_id(task_id)
        if reviewed is not True:
            raise ValueError("explicit resume review confirmation is required")
        data = self._read()
        record = data["tasks"].get(task_id)
        if not isinstance(record, dict) or record.get("held") is not False:
            raise ValueError("task must be explicitly resumed before review")
        if record.get("resume_requires_review") is not True:
            raise ValueError("task has no pending resume review")
        record["resume_requires_review"] = False
        record["resume_reviewed_at"] = utc_now()
        self._write(data)

    def task_status(self, task_id: str) -> dict:
        task_id = _safe_id(task_id)
        record = self._read()["tasks"].get(task_id, {})
        if not isinstance(record, dict):
            raise RecoveryStateError("task recovery record invalid")
        # Return a copy, not a mutable reference to internal state.
        return dict(record)


def elapsed_seconds(started_at: str, resumed_at: str) -> float:
    """Calculate recovery duration from timezone-aware ISO timestamps."""
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(resumed_at)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    seconds = (end - start).total_seconds()
    if seconds < 0:
        raise ValueError("resume time precedes failure time")
    return round(seconds, 3)
