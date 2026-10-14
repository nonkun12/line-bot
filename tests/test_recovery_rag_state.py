"""Tests for durable, allowlisted Recovery RAG history."""
import json
import sqlite3

import pytest

from scripts.recovery_rag_state import export_state, import_state


def record(task_id="task-a", status="TIMEOUT", category="timeout", fingerprint="a" * 64):
    return {
        "task_id": task_id,
        "status": status,
        "category": category,
        "fingerprint": fingerprint,
    }


def test_round_trip_is_sanitized_bounded_and_idempotent(tmp_path):
    db = tmp_path / "rag.sqlite3"
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "completed": [], "recovery_rag": [record()]}))
    assert import_state(state, db, "distributed-loop") == 1
    assert import_state(state, db, "distributed-loop") == 1

    exported = tmp_path / "export.json"
    assert export_state(db, exported, "distributed-loop") == 1
    payload = json.loads(exported.read_text())
    assert payload == {"schema_version": 1, "records": [record()]}


def test_import_rejects_unallowlisted_fields_and_status(tmp_path):
    db = tmp_path / "rag.sqlite3"
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "recovery_rag": [dict(record(), raw_error="must not be stored")]
    }))
    # Unknown fields are deliberately discarded; only the fixed schema is imported.
    assert import_state(state, db, "distributed-loop") == 1
    with sqlite3.connect(db) as conn:
        metadata = json.loads(conn.execute(
            "SELECT metadata_json FROM rag_documents"
        ).fetchone()[0])
    assert "raw_error" not in metadata

    state.write_text(json.dumps({"recovery_rag": [record(status="EXECUTE_PATCH")]}))
    with pytest.raises(ValueError, match="allowlisted"):
        import_state(state, db, "distributed-loop")


def test_import_fails_closed_on_invalid_state_and_retention_overflow(tmp_path):
    db = tmp_path / "rag.sqlite3"
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"recovery_rag": "not-a-list"}))
    with pytest.raises(ValueError, match="invalid durable RAG history"):
        import_state(state, db, "distributed-loop")

    state.write_text(json.dumps({"recovery_rag": [record()] * 201}))
    with pytest.raises(ValueError, match="invalid durable RAG history"):
        import_state(state, db, "distributed-loop")


def test_export_is_namespace_and_source_scoped(tmp_path):
    db = tmp_path / "rag.sqlite3"
    from scripts.recovery_rag import record_outcome

    record_outcome(db, namespace="distributed-loop", **record())
    record_outcome(db, namespace="other-loop", **record(task_id="other-task"))
    output = tmp_path / "export.json"
    assert export_state(db, output, "distributed-loop") == 1
    assert json.loads(output.read_text())["records"] == [record()]
