"""SQLite-backed agent workforce registry and bounded task dispatcher.

This is a coordination primitive, not a model runner. A registered agent is not
considered active merely because it exists: it must heartbeat, match task
capabilities, claim work, and return evidence-backed results.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


ACTIVE = frozenset({"ASSIGNED", "RUNNING"})
TERMINAL = frozenset({"PASS", "NO_CHANGE", "BLOCKED", "FAILED"})
STATUSES = ACTIVE | TERMINAL | {"PENDING"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentStatus:
    agent_id: str
    runtime: str
    capabilities: frozenset[str]
    enabled: bool
    available: bool
    heartbeat_at: str | None
    busy_task_id: str | None
    idle_reason: str


@dataclass(frozen=True)
class WorkforceTask:
    task_id: str
    required_capabilities: frozenset[str]
    payload: str
    status: str
    assigned_agent: str | None
    approval_required: bool
    approved: bool
    attempts: int
    evidence: str | None


class AgentWorkforce:
    """Transactional registry/queue; use a genuinely shared DB for multi-host use."""

    def __init__(self, db_path: str | Path, *, heartbeat_ttl_seconds: int = 180) -> None:
        if heartbeat_ttl_seconds < 1:
            raise ValueError("heartbeat_ttl_seconds must be positive")
        self.db_path = str(db_path)
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workforce_agents (
                    agent_id TEXT PRIMARY KEY, runtime TEXT NOT NULL,
                    capabilities TEXT NOT NULL, enabled INTEGER NOT NULL,
                    available INTEGER NOT NULL, heartbeat_at TEXT,
                    busy_task_id TEXT
                );
                CREATE TABLE IF NOT EXISTS workforce_tasks (
                    task_id TEXT PRIMARY KEY, required_capabilities TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL,
                    assigned_agent TEXT, approval_required INTEGER NOT NULL,
                    approved INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    evidence TEXT, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS workforce_ready
                    ON workforce_tasks(status, approved, updated_at);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _bounded_name(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise ValueError(f"{field} must be a non-empty string <= 100 chars")
        return value.strip()

    @staticmethod
    def _caps(values: Iterable[str]) -> frozenset[str]:
        caps = frozenset(values)
        if len(caps) > 32 or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in caps):
            raise ValueError("capabilities must contain <=32 bounded names")
        return caps

    def register(self, agent_id: str, runtime: str, capabilities: Iterable[str], *, enabled: bool = True) -> None:
        agent_id = self._bounded_name(agent_id, "agent_id")
        runtime = self._bounded_name(runtime, "runtime")
        caps = self._caps(capabilities)
        with self._connect() as db:
            db.execute("""
                INSERT INTO workforce_agents
                (agent_id, runtime, capabilities, enabled, available, heartbeat_at, busy_task_id)
                VALUES (?, ?, ?, ?, 0, NULL, NULL)
                ON CONFLICT(agent_id) DO UPDATE SET
                    runtime=excluded.runtime, capabilities=excluded.capabilities,
                    enabled=excluded.enabled
            """, (agent_id, runtime, json.dumps(sorted(caps)), int(enabled)))

    def heartbeat(self, agent_id: str, *, available: bool = True) -> bool:
        agent_id = self._bounded_name(agent_id, "agent_id")
        with self._connect() as db:
            cur = db.execute(
                "UPDATE workforce_agents SET available=?, heartbeat_at=? WHERE agent_id=? AND enabled=1",
                (int(available), _now(), agent_id),
            )
        return cur.rowcount == 1

    def enqueue(self, task_id: str, required_capabilities: Iterable[str], payload: str, *,
                approval_required: bool = True, approved: bool = False) -> None:
        task_id = self._bounded_name(task_id, "task_id")
        caps = self._caps(required_capabilities)
        if not isinstance(payload, str) or not payload.strip() or len(payload) > 4000:
            raise ValueError("payload must be non-empty and <=4000 chars")
        if approval_required and approved:
            raise ValueError("approval cannot be pre-granted at enqueue")
        with self._connect() as db:
            db.execute("""
                INSERT INTO workforce_tasks
                (task_id, required_capabilities, payload, status, approval_required,
                 approved, updated_at)
                VALUES (?, ?, ?, 'PENDING', ?, ?, ?)
            """, (task_id, json.dumps(sorted(caps)), payload, int(approval_required), int(approved), _now()))

    def approve(self, task_id: str) -> bool:
        with self._connect() as db:
            cur = db.execute(
                "UPDATE workforce_tasks SET approved=1, updated_at=? WHERE task_id=? AND status='PENDING' AND approval_required=1 AND approved=0",
                (_now(), task_id),
            )
        return cur.rowcount == 1

    def claim(self, agent_id: str) -> WorkforceTask | None:
        """Atomically assign one approved, capability-matched task to a live agent."""
        agent_id = self._bounded_name(agent_id, "agent_id")
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=self.heartbeat_ttl_seconds)).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            agent = db.execute("SELECT * FROM workforce_agents WHERE agent_id=?", (agent_id,)).fetchone()
            if not agent or not agent["enabled"] or not agent["available"] or not agent["heartbeat_at"] or agent["heartbeat_at"] < cutoff or agent["busy_task_id"]:
                db.rollback()
                return None
            caps = set(json.loads(agent["capabilities"]))
            rows = db.execute("""
                SELECT * FROM workforce_tasks
                WHERE status='PENDING' AND (approval_required=0 OR approved=1)
                ORDER BY updated_at, task_id
            """).fetchall()
            row = next((r for r in rows if set(json.loads(r["required_capabilities"])).issubset(caps)), None)
            if row is None:
                db.commit()
                return None
            changed = db.execute("""
                UPDATE workforce_tasks SET status='ASSIGNED', assigned_agent=?,
                    attempts=attempts+1, updated_at=?
                WHERE task_id=? AND status='PENDING'
            """, (agent_id, _now(), row["task_id"])).rowcount
            if changed != 1:
                db.rollback()
                return None
            db.execute("UPDATE workforce_agents SET busy_task_id=? WHERE agent_id=?", (row["task_id"], agent_id))
            result = db.execute("SELECT * FROM workforce_tasks WHERE task_id=?", (row["task_id"],)).fetchone()
            db.commit()
        return self._task(result)

    def start(self, task_id: str, agent_id: str) -> bool:
        with self._connect() as db:
            cur = db.execute(
                "UPDATE workforce_tasks SET status='RUNNING', updated_at=? WHERE task_id=? AND assigned_agent=? AND status='ASSIGNED'",
                (_now(), task_id, agent_id),
            )
        return cur.rowcount == 1

    def finish(self, task_id: str, agent_id: str, *, status: str, evidence: str) -> bool:
        if status not in TERMINAL:
            raise ValueError("invalid terminal status")
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 4000:
            return False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("""
                UPDATE workforce_tasks SET status=?, evidence=?, updated_at=?
                WHERE task_id=? AND assigned_agent=? AND status='RUNNING'
            """, (status, evidence.strip(), _now(), task_id, agent_id))
            if cur.rowcount == 1:
                db.execute("UPDATE workforce_agents SET busy_task_id=NULL WHERE agent_id=? AND busy_task_id=?", (agent_id, task_id))
            db.commit()
        return cur.rowcount == 1

    def recover(self, task_id: str) -> bool:
        """Requeue interrupted work; never infer success from a lost worker."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT assigned_agent FROM workforce_tasks WHERE task_id=? AND status IN ('ASSIGNED','RUNNING')", (task_id,)).fetchone()
            if row is None:
                db.rollback()
                return False
            db.execute("""
                UPDATE workforce_tasks SET status='PENDING', assigned_agent=NULL,
                    evidence=NULL, updated_at=? WHERE task_id=?
            """, (_now(), task_id))
            db.execute("UPDATE workforce_agents SET busy_task_id=NULL WHERE agent_id=? AND busy_task_id=?", (row["assigned_agent"], task_id))
            db.commit()
        return True

    def agents(self) -> tuple[AgentStatus, ...]:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=self.heartbeat_ttl_seconds)).isoformat()
        with self._connect() as db:
            rows = db.execute("SELECT * FROM workforce_agents ORDER BY agent_id").fetchall()
            pending = db.execute("SELECT required_capabilities FROM workforce_tasks WHERE status='PENDING' AND (approval_required=0 OR approved=1)").fetchall()
        ready_caps = [set(json.loads(r["required_capabilities"])) for r in pending]
        result = []
        for row in rows:
            caps = frozenset(json.loads(row["capabilities"]))
            live = bool(row["heartbeat_at"] and row["heartbeat_at"] >= cutoff)
            if not row["enabled"]:
                reason = "DISABLED"
            elif not live:
                reason = "NO_HEARTBEAT_OR_OFFLINE"
            elif not row["available"]:
                reason = "UNAVAILABLE"
            elif row["busy_task_id"]:
                reason = "WORKING"
            elif any(req.issubset(caps) for req in ready_caps):
                reason = "READY_FOR_ASSIGNMENT"
            else:
                reason = "NO_MATCHING_APPROVED_WORK"
            result.append(AgentStatus(row["agent_id"], row["runtime"], caps, bool(row["enabled"]),
                                      bool(row["available"]), row["heartbeat_at"], row["busy_task_id"], reason))
        return tuple(result)

    def _task(self, row: sqlite3.Row) -> WorkforceTask:
        return WorkforceTask(row["task_id"], frozenset(json.loads(row["required_capabilities"])),
                             row["payload"], row["status"], row["assigned_agent"],
                             bool(row["approval_required"]), bool(row["approved"]),
                             row["attempts"], row["evidence"])


__all__ = ["AgentStatus", "AgentWorkforce", "WorkforceTask"]
