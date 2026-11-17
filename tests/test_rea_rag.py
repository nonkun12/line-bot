from __future__ import annotations

import pytest

from rag_store import RagStore
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



def test_retrieval_skips_malformed_persisted_metadata(tmp_path):
    db = tmp_path / "rag.sqlite3"
    RagStore(db).add_document(
        namespace="distributed-loop",
        source="rea_evaluation",
        source_id="malformed-record",
        title="REA HOLD: risk_unknown",
        content="risk_unknown",
        metadata={
            "task_id": "rea-task-18",
            "status": "HOLD",
            "reason_code": "risk_unknown",
            "evidence_sha256": "c" * 64,
            "changed_file_count": "untrusted text",
        },
    )
    assert build_rea_context(
        db,
        namespace="distributed-loop",
        task_id="next-task",
        instruction="risk リスクを確認",
    ) == ""


@pytest.mark.parametrize("override", [
    {"status": []}, {"status": None}, {"namespace": []}, {"namespace": ""},
])
def test_rejects_non_string_status_and_invalid_namespace(tmp_path, override):
    args = dict(
        namespace="distributed-loop", task_id="rea-task-17", status="HOLD",
        reason_code="risk_unknown", evidence_sha256="d" * 64,
        changed_file_count=1,
    )
    args.update(override)
    with pytest.raises(ValueError):
        record_rea_evaluation(tmp_path / "rag.sqlite3", **args)


def test_context_rejects_invalid_namespace_and_oversized_instruction(tmp_path):
    db = tmp_path / "rag.sqlite3"
    _record(db)
    assert build_rea_context(
        db, namespace=[], task_id="next-task", instruction="test risk"
    ) == ""
    assert build_rea_context(
        db, namespace="distributed-loop", task_id="next-task",
        instruction="x" * 20001,
    ) == ""


def test_retrieval_excludes_current_tasks_own_previous_evaluation(tmp_path):
    db = tmp_path / "rag.sqlite3"
    _record(db)
    context = build_rea_context(
        db,
        namespace="distributed-loop",
        task_id="rea-task-17",
        instruction="Review test evidence and risk",
    )
    assert context == ""


def test_task_id_does_not_create_retrieval_terms(tmp_path):
    db = tmp_path / "rag.sqlite3"
    _record(db)
    context = build_rea_context(
        db,
        namespace="distributed-loop",
        task_id="test-risk-42",
        instruction="Summarize the requested work",
    )
    assert context == ""


def test_retrieval_skips_non_string_persisted_status_without_crashing(tmp_path):
    db = tmp_path / "rag.sqlite3"
    RagStore(db).add_document(
        namespace="distributed-loop",
        source="rea_evaluation",
        source_id="malformed-status",
        title="REA malformed status",
        content="risk_unknown",
        metadata={
            "task_id": "rea-task-19",
            "status": ["HOLD"],
            "reason_code": "risk_unknown",
            "evidence_sha256": "e" * 64,
            "changed_file_count": 1,
        },
    )
    assert build_rea_context(
        db, namespace="distributed-loop", task_id="new-task",
        instruction="Review risk evidence",
    ) == ""



def test_builds_regression_proposals_from_fail_and_hold_history(tmp_path):
    db = tmp_path / "rag.sqlite3"
    record_rea_evaluation(
        db, namespace="distributed-loop", task_id="old-fail",
        status="FAIL", reason_code="verification_failed",
        evidence_sha256="f" * 64, changed_file_count=1,
    )
    record_rea_evaluation(
        db, namespace="distributed-loop", task_id="old-hold",
        status="HOLD", reason_code="risk_unknown",
        evidence_sha256="1" * 64, changed_file_count=0,
    )
    proposals = build_rea_regression_test_proposals(
        db, namespace="distributed-loop", task_id="new-task",
        instruction="Please review tests, evidence and risk",
    )
    assert "proposal only; not executed" in proposals
    assert "verification_failed" in proposals
    assert "risk_unknown" in proposals
    assert "execution authority" in proposals


def test_regression_proposals_exclude_current_task_and_pass_history(tmp_path):
    db = tmp_path / "rag.sqlite3"
    record_rea_evaluation(
        db, namespace="distributed-loop", task_id="same-task",
        status="HOLD", reason_code="risk_unknown",
        evidence_sha256="2" * 64, changed_file_count=0,
    )
    record_rea_evaluation(
        db, namespace="distributed-loop", task_id="passed-task",
        status="PASS", reason_code="artifact_evidence_verified",
        evidence_sha256="3" * 64, changed_file_count=1,
    )
    proposals = build_rea_regression_test_proposals(
        db, namespace="distributed-loop", task_id="same-task",
        instruction="Review risk and test evidence",
    )
    assert proposals == ""


def test_regression_proposals_ignore_unknown_reason_codes_and_bad_inputs(tmp_path):
    db = tmp_path / "rag.sqlite3"
    record_rea_evaluation(
        db, namespace="distributed-loop", task_id="old-task",
        status="HOLD", reason_code="risk_unknown",
        evidence_sha256="4" * 64, changed_file_count=0,
    )
    assert build_rea_regression_test_proposals(
        db, namespace="distributed-loop", task_id="new-task",
        instruction="unrelated summary",
    ) == ""
    assert build_rea_regression_test_proposals(
        db, namespace=[], task_id="new-task", instruction="risk test",
    ) == ""
