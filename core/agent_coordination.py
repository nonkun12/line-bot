"""Durable, provider-neutral coordination events for independent AI workers.

This store coordinates task ownership; it does not execute agents or authorize
merges/deploys. Claims and event appends are serialized across local processes.
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_EVENT_TYPES = frozenset({
    "TASK_CLAIMED",
    "PROGRESS",
    "NEED_INPUT",
    "BLOCKED",
    "RESULT_READY",
    "REVIEW_FEEDBACK",
    "TASK_RELEASED",
})
_MAX_ID = 200
_MAX_PAYLOAD_BYTES = 16_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class CoordinationEvent:
    task_id: str
    event_type: str
    worker_id: str
    timestamp: str
    lease_until: str | None = None
    payload: dict[str, Any] | None = None


class AgentCoordinationStore:
    """Append-only JSONL event ledger with process-safe task leases.

    The ledger is intended for a shared local filesystem. On a remote or
    distributed filesystem, use a database with transactional compare-and-set.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._lock_path.touch(exist_ok=True)

    def _validate(self, task_id: str, worker_id: str, event_type: str,
                  payload: dict[str, Any] | None) -> None:
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > _MAX_ID:
            raise ValueError("task_id must be a non-empty string <= 200 characters")
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > _MAX_ID:
            raise ValueError("worker_id must be a non-empty string <= 200 characters")
        if event_type not in _EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {event_type}")
        if payload is not None:
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
            try:
                encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ValueError("payload must be JSON serializable") from exc
            if len(encoded) > _MAX_PAYLOAD_BYTES:
                raise ValueError("payload exceeds 16000 bytes")

    def _locked(self):
        """Return an open lock handle; caller must close it to release flock."""
        handle = self._lock_path.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _read_unlocked(self) -> list[CoordinationEvent]:
        if not self.path.exists():
            return []
        events: list[CoordinationEvent] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    event = CoordinationEvent(**raw)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise ValueError(f"corrupt coordination ledger at line {line_number}") from exc
                events.append(event)
        return events

    def read_events(self, task_id: str | None = None) -> tuple[CoordinationEvent, ...]:
        lock = self._locked()
        try:
            events = self._read_unlocked()
            if task_id is not None:
                events = [event for event in events if event.task_id == task_id]
            return tuple(events)
        finally:
            lock.close()

    def _append_unlocked(self, event: CoordinationEvent) -> None:
        record = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(record)
            stream.flush()
            os.fsync(stream.fileno())

    def append_event(
        self,
        task_id: str,
        event_type: str,
        worker_id: str,
        *,
        payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> CoordinationEvent:
        self._validate(task_id, worker_id, event_type, payload)
        lock = self._locked()
        try:
            events = self._read_unlocked()
            if event_type != "TASK_CLAIMED":
                self._assert_owner(events, task_id, worker_id, now or _now())
            event = CoordinationEvent(task_id, event_type, worker_id, _iso(now or _now()), None, payload)
            self._append_unlocked(event)
            return event
        finally:
            lock.close()

    @staticmethod
    def _active_claim(events: Iterable[CoordinationEvent], task_id: str) -> CoordinationEvent | None:
        active: CoordinationEvent | None = None
        for event in events:
            if event.task_id != task_id:
                continue
            if event.event_type == "TASK_CLAIMED":
                active = event
            elif event.event_type == "TASK_RELEASED" and active is not None and event.worker_id == active.worker_id:
                active = None
        return active

    def _assert_owner(
        self, events: list[CoordinationEvent], task_id: str, worker_id: str, now: datetime
    ) -> None:
        claim = self._active_claim(events, task_id)
        if claim is None or claim.worker_id != worker_id:
            raise PermissionError("worker does not own the active task lease")
        if claim.lease_until is None or datetime.fromisoformat(claim.lease_until) <= now:
            raise PermissionError("task lease expired; stale worker results are rejected")

    def claim_task(
        self,
        task_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 300,
        now: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CoordinationEvent:
        self._validate(task_id, worker_id, "TASK_CLAIMED", payload)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 1 <= lease_seconds <= 86_400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        instant = now or _now()
        lock = self._locked()
        try:
            events = self._read_unlocked()
            active = self._active_claim(events, task_id)
            if active is not None and active.lease_until is not None:
                if datetime.fromisoformat(active.lease_until) > instant:
                    raise RuntimeError(f"task already leased by worker: {active.worker_id}")
            event = CoordinationEvent(
                task_id=task_id,
                event_type="TASK_CLAIMED",
                worker_id=worker_id,
                timestamp=_iso(instant),
                lease_until=_iso(instant + timedelta(seconds=lease_seconds)),
                payload=payload,
            )
            self._append_unlocked(event)
            return event
        finally:
            lock.close()
