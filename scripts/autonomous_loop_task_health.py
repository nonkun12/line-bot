"""Durable per-task consecutive-failure tracking for the autonomous loop."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_CONSECUTIVE_FAILURES = 3
HISTORY_LIMIT = 10
RESUME_LOG_LIMIT = 20
MAX_COUNTER = 1_000_000
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
COUNTED_FAILURE_STATUSES = frozenset({"FAIL", "TIMEOUT"})
SUCCESS_STATUSES = frozenset({"PASS", "NO_CHANGE"})


def valid_task_id(value: object) -> bool:
    return isinstance(value, str) and TASK_ID_RE.fullmatch(value) is not None


def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _reason(value: object) -> str:
    return CONTROL_RE.sub(" ", str(value or "")).strip()[:120]


def load_task_health(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(state, dict):
        raise ValueError("autonomous loop state must be an object")
    raw = state.get("task_health", {})
    if not isinstance(raw, dict):
        raise ValueError("task_health must be an object")
    for task_id, entry in raw.items():
        if not valid_task_id(task_id) or not isinstance(entry, dict):
            raise ValueError("task_health contains an invalid task entry")
        count = entry.get("consecutive_failures")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_COUNTER:
            raise ValueError(f"invalid failure counter for {task_id}")
        if not isinstance(entry.get("held"), bool):
            raise ValueError(f"invalid held flag for {task_id}")
        if entry["held"] and count < MAX_CONSECUTIVE_FAILURES:
            raise ValueError(f"held task {task_id} has fewer than {MAX_CONSECUTIVE_FAILURES} failures")
        history = entry.get("history", [])
        if not isinstance(history, list) or len(history) > HISTORY_LIMIT:
            raise ValueError(f"invalid failure history for {task_id}")
        for item in history:
            if not isinstance(item, dict) or not isinstance(item.get("status"), str) or not isinstance(item.get("reason"), str):
                raise ValueError(f"invalid failure history entry for {task_id}")
        for key in ("last_status", "last_reason", "last_failed_at", "held_at", "held_reason"):
            value = entry.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"invalid {key} value for {task_id}")
        if entry["held"] and not (entry.get("held_reason") or entry.get("last_reason")):
            raise ValueError(f"held task {task_id} has no failure reason")
    return raw


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "completed": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("autonomous loop state is invalid") from exc
    if not isinstance(data, dict):
        raise ValueError("autonomous loop state must be an object")
    load_task_health(data)
    resume_log = data.get("resume_log", [])
    if not isinstance(resume_log, list) or len(resume_log) > RESUME_LOG_LIMIT:
        raise ValueError("resume_log is invalid")
    if not all(isinstance(item, dict) for item in resume_log):
        raise ValueError("resume_log entries must be objects")
    return data


def write_state(path: Path, state: dict[str, Any]) -> None:
    load_task_health(state)
    resume_log = state.get("resume_log", [])
    if not isinstance(resume_log, list) or len(resume_log) > RESUME_LOG_LIMIT:
        raise ValueError("resume_log is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def held_task_ids(state: dict[str, Any]) -> set[str]:
    return {task_id for task_id, item in load_task_health(state).items() if item["held"]}


def held_details(state: dict[str, Any]) -> list[dict[str, Any]]:
    health = load_task_health(state)
    return [
        {
            "task_id": task_id,
            "consecutive_failures": item["consecutive_failures"],
            "reason": item.get("held_reason") or item.get("last_reason") or "",
            "held_at": item.get("held_at"),
        }
        for task_id, item in sorted(health.items())
        if item["held"]
    ]


def record_task_result(
    state: dict[str, Any],
    task_id: str,
    status: str,
    reason: object = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    if not valid_task_id(task_id):
        raise ValueError("invalid task id")
    health = load_task_health(state)
    entry = health.get(task_id)
    if status in SUCCESS_STATUSES:
        if entry is not None:
            del health[task_id]
            if not health:
                state.pop("task_health", None)
        return {"consecutive_failures": 0, "held": False, "newly_held": False}
    if status not in COUNTED_FAILURE_STATUSES:
        return {
            "consecutive_failures": entry["consecutive_failures"] if entry else 0,
            "held": bool(entry and entry["held"]),
            "newly_held": False,
        }

    timestamp = _stamp(now)
    clean_reason = _reason(reason) or status.lower()
    if entry is None:
        entry = {
            "consecutive_failures": 0, "held": False, "held_at": None,
            "held_reason": None, "history": [],
        }
        health[task_id] = entry
        state["task_health"] = health
    was_held = entry["held"]
    entry["consecutive_failures"] = min(entry["consecutive_failures"] + 1, MAX_COUNTER)
    entry["last_status"] = status
    entry["last_reason"] = clean_reason
    entry["last_failed_at"] = timestamp
    history = list(entry.get("history", []))
    history.append({"at": timestamp, "status": status, "reason": clean_reason})
    entry["history"] = history[-HISTORY_LIMIT:]
    if entry["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES and not was_held:
        entry["held"] = True
        entry["held_at"] = timestamp
        entry["held_reason"] = clean_reason
    return {
        "consecutive_failures": entry["consecutive_failures"],
        "held": entry["held"],
        "newly_held": bool(entry["held"] and not was_held),
    }


def resume_task(state: dict[str, Any], task_id: str, now: datetime | None = None) -> dict[str, Any]:
    if not valid_task_id(task_id):
        raise ValueError("invalid task id")
    health = load_task_health(state)
    entry = health.get(task_id)
    # Resetting a one- or two-failure counter would bypass the retry policy.
    if entry is None or entry.get("held") is not True:
        raise ValueError(f"task {task_id!r} is not on hold and cannot be resumed")
    log = state.get("resume_log", [])
    if not isinstance(log, list) or len(log) > RESUME_LOG_LIMIT:
        raise ValueError("resume_log is invalid")
    audit = {
        "task_id": task_id,
        "at": _stamp(now),
        "was_held": True,
        "previous_consecutive_failures": entry["consecutive_failures"],
        "previous_reason": entry.get("held_reason") or entry.get("last_reason") or "",
    }
    del health[task_id]
    if not health:
        state.pop("task_health", None)
    state["resume_log"] = (log + [audit])[-RESUME_LOG_LIMIT:]
    return audit
