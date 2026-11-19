"""Explicit, revisioned persistence for complete IdeaResearchCycle snapshots.

The caller chooses the local path and namespace. No import-time I/O, scheduling,
agent execution, experiment execution, or approval is performed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3
from typing import Optional

from .idea_ai import Idea
from .idea_evidence import ExperimentEvidenceLedger
from .idea_hypothesis import ExperimentHypothesis
from .idea_research_cycle import IdeaResearchCycle
from .multi_agent import AgentRole, AgentTask
from .idea_workflow import build_idea_workflow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idea_research_cycles (
    namespace TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""
_MAX_PAYLOAD_CHARS = 2_000_000


class CycleRevisionConflict(RuntimeError):
    """Raised when a stored cycle changed since the caller last loaded it."""


@dataclass(frozen=True)
class StoredIdeaResearchCycle:
    namespace: str
    revision: int
    cycle: IdeaResearchCycle
    updated_at: str


def _encode_idea(idea: Idea) -> dict:
    return {
        "idea_id": idea.idea_id,
        "title": idea.title,
        "rationale": idea.rationale,
        "next_step": idea.next_step,
        "style": idea.style,
        "novelty": idea.novelty,
        "positive_impact": idea.positive_impact,
        "safety_boundary": idea.safety_boundary,
        "task": {
            "task_id": idea.task.task_id,
            "role": idea.task.role.value,
            "instruction": idea.task.instruction,
            "resources": sorted(idea.task.resources),
            "depends_on": list(idea.task.depends_on),
            "priority": idea.task.priority,
        },
    }


def _decode_idea(value: object) -> Idea:
    fields = {
        "idea_id", "title", "rationale", "next_step", "style", "novelty",
        "positive_impact", "safety_boundary", "task",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("idea snapshot has an invalid schema")
    task = value["task"]
    task_fields = {"task_id", "role", "instruction", "resources", "depends_on", "priority"}
    if not isinstance(task, dict) or set(task) != task_fields:
        raise ValueError("idea task snapshot has an invalid schema")
    if not isinstance(task["resources"], list) or not isinstance(task["depends_on"], list):
        raise ValueError("idea task collections must be lists")
    agent_task = AgentTask(
        task_id=task["task_id"],
        role=AgentRole(task["role"]),
        instruction=task["instruction"],
        resources=frozenset(task["resources"]),
        depends_on=tuple(task["depends_on"]),
        priority=task["priority"],
    )
    return Idea(
        idea_id=value["idea_id"],
        title=value["title"],
        rationale=value["rationale"],
        next_step=value["next_step"],
        task=agent_task,
        style=value["style"],
        novelty=value["novelty"],
        positive_impact=value["positive_impact"],
        safety_boundary=value["safety_boundary"],
    )


def _encode_cycle(cycle: IdeaResearchCycle) -> str:
    if not isinstance(cycle, IdeaResearchCycle):
        raise TypeError("cycle must be an IdeaResearchCycle")
    payload = {
        "schema_version": 1,
        "focus": cycle.focus,
        "context": list(cycle.context),
        "ideas": [_encode_idea(idea) for idea in cycle.ideas],
        "hypotheses": [asdict(item) for item in cycle.hypotheses],
        "ledger": json.loads(cycle.ledger.to_json()),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded) > _MAX_PAYLOAD_CHARS:
        raise ValueError("cycle snapshot exceeds 2MB")
    return encoded


def _decode_cycle(payload: str) -> IdeaResearchCycle:
    if not isinstance(payload, str) or len(payload) > _MAX_PAYLOAD_CHARS:
        raise ValueError("cycle payload must be a string no larger than 2MB")
    try:
        data = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("cycle payload must be valid JSON") from exc
    expected = {"schema_version", "focus", "context", "ideas", "hypotheses", "ledger"}
    if not isinstance(data, dict) or set(data) != expected or data["schema_version"] != 1:
        raise ValueError("unsupported or invalid cycle snapshot schema")
    if not isinstance(data["focus"], str) or not data["focus"].strip():
        raise ValueError("cycle focus is required")
    if not isinstance(data["context"], list) or any(not isinstance(item, str) for item in data["context"]):
        raise ValueError("cycle context must be a list of strings")
    if not isinstance(data["ideas"], list) or not 1 <= len(data["ideas"]) <= 5:
        raise ValueError("cycle ideas must contain 1 to 5 items")
    if not isinstance(data["hypotheses"], list) or len(data["hypotheses"]) > 100:
        raise ValueError("cycle hypotheses must be a list of at most 100 items")
    ideas = tuple(_decode_idea(item) for item in data["ideas"])
    hypothesis_fields = {
        "hypothesis_id", "statement", "prediction", "metric", "direction", "baseline",
        "success_threshold", "failure_threshold", "baseline_source", "measurement_method",
        "evidence_requirements", "reproducibility_steps",
    }
    hypotheses = []
    for item in data["hypotheses"]:
        if not isinstance(item, dict) or set(item) != hypothesis_fields:
            raise ValueError("hypothesis snapshot has an invalid schema")
        values = dict(item)
        for key in ("evidence_requirements", "reproducibility_steps"):
            if not isinstance(values[key], list):
                raise ValueError("hypothesis list fields must be lists")
            values[key] = tuple(values[key])
        hypotheses.append(ExperimentHypothesis(**values))
    ledger = ExperimentEvidenceLedger.from_json(json.dumps(data["ledger"], separators=(",", ":")))
    return IdeaResearchCycle(
        focus=data["focus"],
        context=tuple(data["context"]),
        ideas=ideas,
        workflow=build_idea_workflow(data["focus"], context=tuple(data["context"])),
        hypotheses=tuple(hypotheses),
        ledger=ledger,
    )


class SQLiteIdeaResearchCycleStore:
    """Persist and restore complete immutable research cycles with CAS revisions."""

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        if not isinstance(database_path, (str, os.PathLike)):
            raise TypeError("database_path must be a filesystem path")
        raw = os.fspath(database_path)
        if not raw or raw == ":memory:" or raw.startswith("file:"):
            raise ValueError("an explicit on-disk SQLite path is required")
        self.database_path = Path(raw).expanduser()
        if self.database_path.exists() and self.database_path.is_dir():
            raise ValueError("database_path must identify a file")

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 120:
            raise ValueError("namespace must be non-empty and <= 120 characters")

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.database_path.exists()
        connection = sqlite3.connect(str(self.database_path), timeout=5.0, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute(_SCHEMA)
            if not existed:
                os.chmod(self.database_path, 0o600)
            return connection
        except Exception:
            connection.close()
            raise

    def save(
        self, namespace: str, cycle: IdeaResearchCycle, *, expected_revision: int
    ) -> int:
        self._validate_namespace(namespace)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        payload = _encode_cycle(cycle)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM idea_research_cycles WHERE namespace = ?", (namespace,)
            ).fetchone()
            current = row[0] if row else 0
            if current != expected_revision:
                raise CycleRevisionConflict(f"expected revision {expected_revision}, found {current}")
            revision = current + 1
            connection.execute(
                """INSERT INTO idea_research_cycles(namespace, revision, payload, updated_at)
                VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(namespace) DO UPDATE SET revision=excluded.revision,
                payload=excluded.payload, updated_at=excluded.updated_at""",
                (namespace, revision, payload),
            )
            connection.execute("COMMIT")
            return revision
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def load(self, namespace: str) -> Optional[StoredIdeaResearchCycle]:
        self._validate_namespace(namespace)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT revision, payload, updated_at FROM idea_research_cycles WHERE namespace = ?",
                (namespace,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        revision, payload, updated_at = row
        return StoredIdeaResearchCycle(namespace, revision, _decode_cycle(payload), updated_at)


__all__ = [
    "CycleRevisionConflict",
    "SQLiteIdeaResearchCycleStore",
    "StoredIdeaResearchCycle",
]
