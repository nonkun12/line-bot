"""Explicit local SQLite persistence for the idea evidence ledger.

No database is opened at import time. Callers must supply a database path and
namespace. Writes use SQLite transactions and optimistic revision checks.
This module never schedules work or grants experiment execution permission.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Optional

from .idea_evidence import ExperimentEvidenceLedger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idea_evidence_snapshots (
    namespace TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS idea_cycle_snapshots (
    namespace TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


class RevisionConflict(RuntimeError):
    """Raised when a snapshot changed since the caller last loaded it."""


@dataclass(frozen=True)
class StoredCycleSnapshot:
    namespace: str
    revision: int
    cycle: object
    updated_at: str


@dataclass(frozen=True)
class StoredEvidenceSnapshot:
    namespace: str
    revision: int
    ledger: ExperimentEvidenceLedger
    updated_at: str


class SQLiteIdeaEvidenceStore:
    """Small local-only store; every operation is explicit and transactional."""

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        if not isinstance(database_path, (str, os.PathLike)):
            raise TypeError("database_path must be a filesystem path")
        raw_path = os.fspath(database_path)
        if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
            raise ValueError("an explicit on-disk SQLite path is required")
        self.database_path = Path(raw_path).expanduser()
        if self.database_path.exists() and self.database_path.is_dir():
            raise ValueError("database_path must identify a file")

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.database_path.exists()
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        if not existed:
            try:
                os.chmod(self.database_path, 0o600)
            except OSError:
                connection.close()
                raise
        return connection

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 120:
            raise ValueError("namespace must be non-empty and <= 120 characters")

    def load(self, namespace: str) -> Optional[StoredEvidenceSnapshot]:
        self._validate_namespace(namespace)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT revision, payload, updated_at "
                "FROM idea_evidence_snapshots WHERE namespace = ?",
                (namespace,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        revision, payload, updated_at = row
        return StoredEvidenceSnapshot(
            namespace=namespace,
            revision=revision,
            ledger=ExperimentEvidenceLedger.from_json(payload),
            updated_at=updated_at,
        )

    def save(
        self,
        namespace: str,
        ledger: ExperimentEvidenceLedger,
        *,
        expected_revision: int,
    ) -> int:
        self._validate_namespace(namespace)
        if not isinstance(ledger, ExperimentEvidenceLedger):
            raise TypeError("ledger must be an ExperimentEvidenceLedger")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        payload = ledger.to_json()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM idea_evidence_snapshots WHERE namespace = ?",
                (namespace,),
            ).fetchone()
            current_revision = row[0] if row else 0
            if expected_revision != current_revision:
                raise RevisionConflict(
                    f"expected revision {expected_revision}, found {current_revision}"
                )
            next_revision = current_revision + 1
            connection.execute(
                """
                INSERT INTO idea_evidence_snapshots
                    (namespace, revision, payload, updated_at)
                VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(namespace) DO UPDATE SET
                    revision = excluded.revision,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (namespace, next_revision, payload),
            )
            connection.execute("COMMIT")
            return next_revision
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def save_cycle(self, namespace: str, cycle, *, expected_revision: int) -> int:
        """Persist a complete validated research cycle using optimistic revisions."""
        from .idea_research_cycle import IdeaResearchCycle

        self._validate_namespace(namespace)
        if not isinstance(cycle, IdeaResearchCycle):
            raise TypeError("cycle must be an IdeaResearchCycle")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        payload = cycle.to_json()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT revision FROM idea_cycle_snapshots WHERE namespace = ?", (namespace,)).fetchone()
            current_revision = row[0] if row else 0
            if expected_revision != current_revision:
                raise RevisionConflict(f"expected revision {expected_revision}, found {current_revision}")
            next_revision = current_revision + 1
            connection.execute("INSERT INTO idea_cycle_snapshots (namespace, revision, payload, updated_at) VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) ON CONFLICT(namespace) DO UPDATE SET revision = excluded.revision, payload = excluded.payload, updated_at = excluded.updated_at", (namespace, next_revision, payload))
            connection.execute("COMMIT")
            return next_revision
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def load_cycle(self, namespace: str):
        """Load and validate a complete cycle snapshot; return None when absent."""
        from .idea_research_cycle import IdeaResearchCycle
        self._validate_namespace(namespace)
        connection = self._connect()
        try:
            row = connection.execute("SELECT revision, payload, updated_at FROM idea_cycle_snapshots WHERE namespace = ?", (namespace,)).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        revision, payload, updated_at = row
        return StoredCycleSnapshot(namespace, revision, IdeaResearchCycle.from_json(payload), updated_at)

    def delete(self, namespace: str, *, expected_revision: int) -> bool:
        """Delete only the exact revision a caller reviewed; never wildcard-delete."""
        self._validate_namespace(namespace)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM idea_evidence_snapshots WHERE namespace = ? AND revision = ?",
                (namespace, expected_revision),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT revision FROM idea_evidence_snapshots WHERE namespace = ?",
                    (namespace,),
                ).fetchone()
                if row is not None:
                    raise RevisionConflict(
                        f"expected revision {expected_revision}, found {row[0]}"
                    )
            connection.execute("COMMIT")
            return cursor.rowcount == 1
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


__all__ = [
    "RevisionConflict",
    "SQLiteIdeaEvidenceStore",
    "StoredEvidenceSnapshot",
    "StoredCycleSnapshot",
]
