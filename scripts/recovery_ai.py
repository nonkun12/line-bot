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
REPAIRABLE_CATEGORIES = frozenset({"test_regression", "timeout", "process_crash"})
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
        data["tasks"][task_id] = {
            "consecutive_failures": count,
            "last_category": category,
            "last_fingerprint": fingerprint,
            "fingerprints": (history + [fingerprint])[-20:],
            "same_fingerprint_attempts": same_count + 1,
            "held": bool(previous.get("held", False)),
            "updated_at": now,
        }
        record = data["tasks"][task_id]
        if category == "state_persistence_failure":
            action, reason, delay, human = "STOP_FAIL_CLOSED", "state_persistence_failure", 0, True
        elif record["held"] or count >= HOLD_AFTER_FAILURES or category in NON_REPAIRABLE_CATEGORIES:
            record["held"] = True
            action, reason, delay, human = "HOLD", "task_held_for_safety", 0, True
        elif category in TRANSIENT_CATEGORIES and transient_attempt <= MAX_TRANSIENT_RETRIES:
            action, reason, delay, human = "RETRY", "bounded_transient_retry", min(30 * (2 ** (transient_attempt - 1)), 120), False
        elif category in REPAIRABLE_CATEGORIES and same_count < MAX_REPAIR_ATTEMPTS_PER_FINGERPRINT:
            action, reason, delay, human = "REPAIR_ONCE", "bounded_repair_attempt", 0, False
        else:
            record["held"] = True
            action, reason, delay, human = "HOLD", "repair_budget_exhausted", 0, True
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

    def all_task_statuses(self) -> dict[str, dict]:
        """Return validated copies of every task record, including held tasks off-queue."""
        tasks = self._read()["tasks"]
        result: dict[str, dict] = {}
        for task_id, record in tasks.items():
            _safe_id(task_id)
            if not isinstance(record, dict):
                raise RecoveryStateError("task recovery record invalid")
            result[task_id] = dict(record)
        return result


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
