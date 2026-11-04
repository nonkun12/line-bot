"""Durable, owner-scoped persistence for resumable audiovisual Goal chains."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import db
from agents.media.goal_job_chain_state import derive_goal_job_chain_state


class GoalChainConflictError(RuntimeError):
    """A stale or conflicting Goal-chain update was rejected."""


_EVENT_TYPES = frozenset({"checkpoint", "stage_completed", "human_approved", "hold_raised"})


def _owner(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ValueError("user_id must contain 1..128 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("user_id contains control characters")
    return value.strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ensure_schema() -> None:
    with db.get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_media_chains (
                goal_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version >= 1),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_media_chain_events (
                goal_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(goal_id, version)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_goal_media_chains_user "
            "ON goal_media_chains(user_id, updated_at)"
        )


def _decode(row: tuple) -> dict[str, Any]:
    return {
        "goal_id": row[0],
        "user_id": row[1],
        "plan": json.loads(row[2]),
        "plan_sha256": row[3],
        "state": json.loads(row[4]),
        "version": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def _select(conn, user_id: str, goal_id: str):
    return conn.execute(
        """SELECT goal_id,user_id,plan_json,plan_sha256,snapshot_json,version,created_at,updated_at
           FROM goal_media_chains WHERE goal_id=? AND user_id=?""",
        (goal_id, user_id),
    ).fetchone()


def create_or_resume_goal_chain(user_id: str, plan: object) -> dict[str, Any]:
    """Create once; identical retries return the existing durable state."""
    _ensure_schema()
    owner = _owner(user_id)
    initial = derive_goal_job_chain_state(plan)
    goal_id = initial["goal_id"]
    plan_json = _json(plan)
    plan_hash = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
    state_json = _json(initial)

    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT goal_id,user_id,plan_json,plan_sha256,snapshot_json,version,created_at,updated_at
               FROM goal_media_chains WHERE goal_id=?""",
            (goal_id,),
        ).fetchone()
        if row is not None:
            current = _decode(row)
            if current["user_id"] != owner or current["plan_sha256"] != plan_hash:
                raise GoalChainConflictError("goal_id already belongs to another owner or plan")
            return current
        conn.execute(
            """INSERT INTO goal_media_chains
               (goal_id,user_id,plan_json,plan_sha256,snapshot_json,version)
               VALUES (?,?,?,?,?,1)""",
            (goal_id, owner, plan_json, plan_hash, state_json),
        )
        conn.execute(
            """INSERT INTO goal_media_chain_events(goal_id,version,event_type,snapshot_json)
               VALUES (?,1,'created',?)""",
            (goal_id, state_json),
        )
        row = _select(conn, owner, goal_id)
    return _decode(row)


def get_goal_chain(user_id: str, goal_id: str) -> dict[str, Any] | None:
    _ensure_schema()
    owner = _owner(user_id)
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise ValueError("goal_id is required")
    with db.get_conn() as conn:
        row = _select(conn, owner, goal_id.strip())
    return _decode(row) if row is not None else None


def record_goal_chain_evidence(
    user_id: str,
    goal_id: str,
    *,
    expected_version: int,
    completed_job_ids: object | None = None,
    approved_gate_job_ids: object | None = None,
    held_job_ids: object | None = None,
    event_type: str = "checkpoint",
) -> dict[str, Any]:
    """Persist monotonic evidence using optimistic concurrency and idempotent retries."""
    _ensure_schema()
    owner = _owner(user_id)
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise ValueError("goal_id is required")
    if type(expected_version) is not int or expected_version < 1:
        raise ValueError("expected_version must be a positive integer")
    if event_type not in _EVENT_TYPES:
        raise ValueError("event_type is not supported")

    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _select(conn, owner, goal_id.strip())
        if row is None:
            raise KeyError("goal chain not found")
        current = _decode(row)
        old = current["state"]["snapshot"]
        completed = old["completed_job_ids"] if completed_job_ids is None else completed_job_ids
        approved = old["approved_gate_job_ids"] if approved_gate_job_ids is None else approved_gate_job_ids
        held = old["held_job_ids"] if held_job_ids is None else held_job_ids
        next_state = derive_goal_job_chain_state(
            current["plan"],
            completed_job_ids=completed,
            approved_gate_job_ids=approved,
            held_job_ids=held,
        )
        new = next_state["snapshot"]
        for key in ("completed_job_ids", "approved_gate_job_ids", "held_job_ids"):
            if not set(old[key]).issubset(set(new[key])):
                raise ValueError(f"{key} evidence is append-only and cannot be removed")

        encoded = _json(next_state)
        if encoded == _json(current["state"]):
            return current
        if expected_version != current["version"]:
            raise GoalChainConflictError("goal chain version conflict; reload before updating")
        next_version = current["version"] + 1
        cursor = conn.execute(
            """UPDATE goal_media_chains SET snapshot_json=?,version=?,updated_at=CURRENT_TIMESTAMP
               WHERE goal_id=? AND user_id=? AND version=?""",
            (encoded, next_version, goal_id.strip(), owner, expected_version),
        )
        if cursor.rowcount != 1:
            raise GoalChainConflictError("goal chain version conflict; reload before updating")
        conn.execute(
            """INSERT INTO goal_media_chain_events(goal_id,version,event_type,snapshot_json)
               VALUES (?,?,?,?)""",
            (goal_id.strip(), next_version, event_type, encoded),
        )
        row = _select(conn, owner, goal_id.strip())
    return _decode(row)


def get_goal_chain_history(user_id: str, goal_id: str) -> list[dict[str, Any]]:
    _ensure_schema()
    owner = _owner(user_id)
    if get_goal_chain(owner, goal_id) is None:
        return []
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT e.version,e.event_type,e.snapshot_json,e.created_at
               FROM goal_media_chain_events e
               JOIN goal_media_chains c ON c.goal_id=e.goal_id
               WHERE e.goal_id=? AND c.user_id=? ORDER BY e.version""",
            (goal_id.strip(), owner),
        ).fetchall()
    return [
        {"version": row[0], "event_type": row[1], "state": json.loads(row[2]), "created_at": row[3]}
        for row in rows
    ]


__all__ = [
    "GoalChainConflictError",
    "create_or_resume_goal_chain",
    "get_goal_chain",
    "get_goal_chain_history",
    "record_goal_chain_evidence",
]
