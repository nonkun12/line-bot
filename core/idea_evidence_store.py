"""Explicit, append-only SQLite persistence for experiment evidence.

Nothing is opened or written until a caller constructs the store and calls append.
The store never runs experiments or changes verification status.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.idea_evidence import ExperimentEvidence


class ExperimentEvidenceStore:
    """Small local evidence ledger; experiment IDs are immutable unique keys."""

    def __init__(self, database_path: str | Path) -> None:
        raw_path = Path(database_path).expanduser()
        if str(raw_path) == ":memory:":
            raise ValueError("a persistent filesystem path is required")
        if raw_path.is_symlink():
            raise ValueError("database path must not be a symlink")
        if not raw_path.parent.is_dir():
            raise FileNotFoundError("database parent directory must already exist")
        self._path = raw_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_evidence (
                    experiment_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            # Some filesystems do not support POSIX permission modes.
            pass

    @staticmethod
    def _serialize(record: ExperimentEvidence) -> str:
        return json.dumps(
            {
                "experiment_id": record.experiment_id,
                "hypothesis_id": record.hypothesis_id,
                "style": record.style,
                "measured_value": record.measured_value,
                "evidence_refs": record.evidence_refs,
                "code_revision": record.code_revision,
                "environment": record.environment,
                "verification_status": record.verification_status,
                "verified_by": record.verified_by,
                "verification_signature": record.verification_signature,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize(payload: str) -> ExperimentEvidence:
        values = json.loads(payload)
        values["evidence_refs"] = tuple(values["evidence_refs"])
        return ExperimentEvidence(**values)

    def append(self, record: ExperimentEvidence) -> None:
        """Append a record once; never overwrite an existing experiment ID."""
        if not isinstance(record, ExperimentEvidence):
            raise TypeError("record must be an ExperimentEvidence")
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO experiment_evidence
                        (experiment_id, hypothesis_id, payload)
                    VALUES (?, ?, ?)
                    """,
                    (record.experiment_id, record.hypothesis_id, self._serialize(record)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"experiment_id already exists: {record.experiment_id}") from exc

    def list_for_hypothesis(self, hypothesis_id: str) -> tuple[ExperimentEvidence, ...]:
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            raise ValueError("hypothesis_id is required")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM experiment_evidence
                WHERE hypothesis_id = ?
                ORDER BY created_at, experiment_id
                """,
                (hypothesis_id,),
            ).fetchall()
        return tuple(self._deserialize(row[0]) for row in rows)


__all__ = ["ExperimentEvidenceStore"]
