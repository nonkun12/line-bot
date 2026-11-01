"""Append-only, idempotent event contract shared by cooperating agents.

Events carry bounded metadata and references, not prompts, credentials, or note bodies.
Existing job queues remain authoritative for execution; this log correlates them.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from contextlib import closing
from types import MappingProxyType
from typing import Any, Mapping

import db

_MAX_ID = 200
_MAX_SHORT = 128
_MAX_PAYLOAD_BYTES = 4096
_VALID_STATUSES = frozenset({"PENDING", "RUNNING", "COMPLETED", "FAILED", "BLOCKED", "NOT_RUN"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_PAYLOAD_KEYS = frozenset({
    "proposal_ref", "count", "runtime_success", "integration_ready",
    "rounds", "repair_attempts", "changed_resource_count",
})
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,255}$")


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    task_id: str
    agent_id: str
    role: str
    event_type: str
    status: str
    parent_task_id: str | None = None
    request_id: str | None = None
    next_agent: str | None = None
    result_sha: str | None = None
    payload: Mapping[str, str | int | float | bool | None] | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "task_id", "agent_id", "role", "event_type"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > _MAX_ID:
                raise ValueError(f"{name} must be a non-empty string <= {_MAX_ID} characters")
        for name in ("parent_task_id", "request_id", "next_agent"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip() or len(value) > _MAX_SHORT
            ):
                raise ValueError(f"{name} must be null or a non-empty string <= {_MAX_SHORT} characters")
        if not isinstance(self.status, str) or self.status not in _VALID_STATUSES:
            raise ValueError("status is not allowlisted")
        if self.result_sha is not None and (
            not isinstance(self.result_sha, str) or not _SHA256.fullmatch(self.result_sha)
        ):
            raise ValueError("result_sha must be a lowercase SHA-256 digest")
        payload = dict(self.payload or {})
        if len(payload) > 32:
            raise ValueError("payload must contain at most 32 fields")
        for key, value in payload.items():
            if not isinstance(key, str) or key not in _ALLOWED_PAYLOAD_KEYS:
                raise ValueError("payload key is not allowlisted")
            if value is not None and (
                isinstance(value, (dict, list, tuple, set))
                or not isinstance(value, (str, int, float, bool))
            ):
                raise ValueError("payload values must be scalar metadata")
            if isinstance(value, str) and (
                len(value) > 256 or not _SAFE_REFERENCE.fullmatch(value)
            ):
                raise ValueError("payload strings must be short opaque references")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("payload numbers must be finite")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("payload exceeds 4096 UTF-8 bytes")
        object.__setattr__(self, "payload", MappingProxyType(payload))


def _canonical(event: AgentEvent) -> dict[str, Any]:
    # Revalidate at the persistence boundary as defense in depth.
    payload = dict(event.payload or {})
    for key, value in payload.items():
        if key not in _ALLOWED_PAYLOAD_KEYS:
            raise ValueError("payload key is not allowlisted")
        if isinstance(value, str) and (len(value) > 256 or not _SAFE_REFERENCE.fullmatch(value)):
            raise ValueError("payload strings must be short opaque references")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("payload numbers must be finite")
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(payload_json.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds 4096 UTF-8 bytes")
    return {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "parent_task_id": event.parent_task_id,
        "request_id": event.request_id,
        "agent_id": event.agent_id,
        "role": event.role,
        "event_type": event.event_type,
        "status": event.status,
        "next_agent": event.next_agent,
        "result_sha": event.result_sha,
        "payload_json": payload_json,
    }


def record_agent_event(event: AgentEvent) -> bool:
    """Insert once; identical retries are harmless, conflicting event-ID reuse fails."""
    if not isinstance(event, AgentEvent):
        raise TypeError("event must be an AgentEvent")
    values = _canonical(event)
    with closing(db.get_conn()) as conn, conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO agent_task_events(
                event_id, task_id, parent_task_id, request_id, agent_id, role,
                event_type, status, next_agent, result_sha, payload_json
            ) VALUES (
                :event_id, :task_id, :parent_task_id, :request_id, :agent_id, :role,
                :event_type, :status, :next_agent, :result_sha, :payload_json
            )
            """,
            values,
        )
        if cursor.rowcount == 1:
            return True
        row = conn.execute(
            """
            SELECT task_id, parent_task_id, request_id, agent_id, role, event_type,
                   status, next_agent, result_sha, payload_json
            FROM agent_task_events WHERE event_id=?
            """,
            (event.event_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("event insert outcome could not be verified")
    keys = (
        "task_id", "parent_task_id", "request_id", "agent_id", "role", "event_type",
        "status", "next_agent", "result_sha", "payload_json",
    )
    if dict(zip(keys, row)) != {key: value for key, value in values.items() if key != "event_id"}:
        raise ValueError("event_id already exists with different event content")
    return False


def list_agent_events(task_id: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > _MAX_ID:
        raise ValueError("task_id is required and must be <= 200 characters")
    with closing(db.get_conn()) as conn, conn:
        rows = conn.execute(
            """
            SELECT event_id, task_id, parent_task_id, request_id, agent_id, role,
                   event_type, status, next_agent, result_sha, payload_json, created_at
            FROM agent_task_events WHERE task_id=? ORDER BY id
            """,
            (task_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(zip(
            ("event_id", "task_id", "parent_task_id", "request_id", "agent_id", "role",
             "event_type", "status", "next_agent", "result_sha", "payload_json", "created_at"),
            row,
        ))
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return tuple(result)


__all__ = ["AgentEvent", "record_agent_event", "list_agent_events"]
