from __future__ import annotations

import sqlite3

import pytest

from core.idea_evidence import ExperimentEvidence, ExperimentEvidenceLedger
from core.idea_evidence_store import RevisionConflict, SQLiteIdeaEvidenceStore


def ledger():
    item = ExperimentEvidence(
        hypothesis_id="persist-h1",
        style="recombine",
        result="unverified",
        observed_value=90.0,
        metric="latency ms",
        source_ref="artifact://persist/run-1",
        commit_sha="a" * 40,
        environment="local-test",
        sample_count=10,
        measured_at="2026-11-19T00:00:00Z",
        evidence_sha256="b" * 64,
    )
    return ExperimentEvidenceLedger().append(item)


def test_store_round_trip_and_revision_increment(tmp_path):
    store = SQLiteIdeaEvidenceStore(tmp_path / "state" / "ideas.sqlite3")
    assert store.load("idea-ai") is None
    first = store.save("idea-ai", ledger(), expected_revision=0)
    assert first == 1
    loaded = store.load("idea-ai")
    assert loaded is not None
    assert loaded.revision == 1
    assert loaded.ledger == ledger()

    second = store.save("idea-ai", ExperimentEvidenceLedger(), expected_revision=1)
    assert second == 2
    assert store.load("idea-ai").revision == 2


def test_store_rejects_stale_writer_without_overwriting(tmp_path):
    store = SQLiteIdeaEvidenceStore(tmp_path / "ideas.sqlite3")
    store.save("idea-ai", ledger(), expected_revision=0)
    with pytest.raises(RevisionConflict):
        store.save("idea-ai", ExperimentEvidenceLedger(), expected_revision=0)
    assert store.load("idea-ai").ledger == ledger()


def test_store_delete_requires_exact_revision(tmp_path):
    store = SQLiteIdeaEvidenceStore(tmp_path / "ideas.sqlite3")
    store.save("idea-ai", ledger(), expected_revision=0)
    with pytest.raises(RevisionConflict):
        store.delete("idea-ai", expected_revision=2)
    assert store.load("idea-ai") is not None
    assert store.delete("idea-ai", expected_revision=1) is True
    assert store.load("idea-ai") is None
    assert store.delete("idea-ai", expected_revision=1) is False


def test_store_validates_paths_namespaces_and_types(tmp_path):
    with pytest.raises(ValueError):
        SQLiteIdeaEvidenceStore(":memory:")
    with pytest.raises(ValueError):
        SQLiteIdeaEvidenceStore(tmp_path)
    store = SQLiteIdeaEvidenceStore(tmp_path / "ideas.sqlite3")
    with pytest.raises(ValueError):
        store.load(" " )
    with pytest.raises(TypeError):
        store.save("idea-ai", object())
    with pytest.raises(ValueError):
        store.save("idea-ai", ledger(), expected_revision=-1)


def test_new_database_is_private_and_schema_is_sqlite(tmp_path):
    path = tmp_path / "ideas.sqlite3"
    store = SQLiteIdeaEvidenceStore(path)
    store.save("idea-ai", ledger(), expected_revision=0)
    assert path.exists()
    assert sqlite3.connect(path).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='idea_evidence_snapshots'"
    ).fetchone() is not None
    assert path.stat().st_mode & 0o077 == 0
