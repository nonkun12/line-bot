from __future__ import annotations

import pytest

from scripts.rea_rag import build_rea_context, record_rea_evaluation


def _record(db):
    return record_rea_evaluation(
        db,
        namespace="distributed-loop",
        task_id="rea-task-17",
        status="HOLD",
        reason_code="risk_unknown",
        evidence_sha256="a" * 64,
        changed_file_count=2,
    )


def test_records_only_sanitized_rea_metadata_and_is_idempotent(tmp_path):
    db = tmp_path / "rag.sqlite3"
    first = _record(db)
    second = _record(db)
    assert first["id"] == second["id"]


def test_retrieves_relevant_rea_history_as_advisory_context(tmp_path):
    db = tmp_path / "rag.sqlite3"
    _record(db)
    context = build_rea_context(
        db,
        namespace="distributed-loop",
        task_id="new-task",
        instruction="Review test evidence and unknown risk",
    )
    assert "Historical REA outcomes" in context
    assert "status=HOLD" in context
    assert "reason=risk_unknown" in context
    assert "not instructions" in context
    assert "a" * 64 not in context


def test_namespace_isolation_and_empty_cache(tmp_path):
    db = tmp_path / "rag.sqlite3"
    _record(db)
    assert build_rea_context(
        db, namespace="other", task_id="new-task", instruction="test risk"
    ) == ""
    assert build_rea_context(
        tmp_path / "missing.sqlite3", namespace="distributed-loop",
        task_id="new-task", instruction="test risk"
    ) == ""


@pytest.mark.parametrize("override", [
    {"status": "SUCCESS"}, {"reason_code": "run shell"},
    {"task_id": "../secret"}, {"evidence_sha256": "not-a-hash"},
    {"changed_file_count": True}, {"changed_file_count": -1},
])
def test_rejects_untrusted_rea_fields(tmp_path, override):
    args = dict(
        namespace="distributed-loop", task_id="rea-task-17", status="HOLD",
        reason_code="risk_unknown", evidence_sha256="b" * 64,
        changed_file_count=1,
    )
    args.update(override)
    with pytest.raises(ValueError):
        record_rea_evaluation(tmp_path / "rag.sqlite3", **args)



def test_retrieves_rea_history_for_japanese_task_instruction(tmp_path):
    db = tmp_path / "rag.sqlite3"
    _record(db)
    context = build_rea_context(
        db,
        namespace="distributed-loop",
        task_id="next-task",
        instruction="テスト証拠とリスクを確認して",
    )
    assert "Historical REA outcomes" in context
    assert "status=HOLD" in context
    assert "risk_unknown" in context
