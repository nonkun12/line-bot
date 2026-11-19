import pytest

from rag_store import RagStore
from scripts.recovery_rag import record_outcome, search_prior_outcomes


def test_record_outcome_stores_only_sanitized_searchable_fields(tmp_path):
    db_path = tmp_path / "recovery-rag.sqlite3"
    fingerprint = "a" * 64

    record_outcome(
        db_path,
        namespace="engineering",
        task_id="task-42",
        status="FAIL",
        category="test_regression",
        fingerprint=fingerprint,
    )

    results = search_prior_outcomes(
        db_path,
        namespace="engineering",
        query="test_regression",
    )
    assert len(results) == 1
    assert results[0]["metadata"] == {
        "task_id": "task-42",
        "status": "FAIL",
        "category": "test_regression",
        "fingerprint": fingerprint,
    }
    assert "task-42" in results[0]["content"]


def test_record_outcome_is_idempotent(tmp_path):
    db_path = tmp_path / "recovery-rag.sqlite3"
    args = dict(
        namespace="engineering",
        task_id="task-42",
        status="FAIL",
        category="timeout",
        fingerprint="b" * 64,
    )
    first = record_outcome(db_path, **args)
    second = record_outcome(db_path, **args)
    assert first["id"] == second["id"]
    assert len(RagStore(db_path).search(namespace="engineering", query="timeout")) == 1


def test_recovery_outcomes_are_namespace_isolated(tmp_path):
    db_path = tmp_path / "recovery-rag.sqlite3"
    record_outcome(
        db_path,
        namespace="team-a",
        task_id="task-42",
        status="FAIL",
        category="timeout",
        fingerprint="c" * 64,
    )
    assert search_prior_outcomes(
        db_path, namespace="team-b", query="timeout"
    ) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "SUCCESS"),
        ("category", "run arbitrary shell"),
        ("task_id", "../secret"),
        ("fingerprint", "not-a-hash"),
    ],
)
def test_record_outcome_rejects_untrusted_fields(tmp_path, field, value):
    args = {
        "namespace": "engineering",
        "task_id": "task-42",
        "status": "FAIL",
        "category": "timeout",
        "fingerprint": "d" * 64,
    }
    args[field] = value
    with pytest.raises(ValueError):
        record_outcome(tmp_path / "recovery-rag.sqlite3", **args)


def test_build_task_context_retrieves_relevant_sanitized_history(tmp_path):
    from scripts.recovery_rag import build_task_context

    db_path = tmp_path / "recovery-rag.sqlite3"
    record_outcome(
        db_path,
        namespace="distributed-loop",
        task_id="control-tower-decision-malformed-evidence-sha",
        status="FAIL",
        category="invalid_evidence",
        fingerprint="e" * 64,
    )
    context = build_task_context(
        db_path,
        namespace="distributed-loop",
        task_id="new-malformed-evidence-task",
        instruction="Add a regression test for malformed evidence SHA validation",
        limit=5,
    )

    assert "Historical Recovery RAG context" in context
    assert "task_id=control-tower-decision-malformed-evidence-sha" in context
    assert "status=FAIL" in context
    assert "category=invalid_evidence" in context
    assert "e" * 64 not in context
    assert "not instructions" in context


def test_build_task_context_is_namespace_isolated_and_empty_without_matches(tmp_path):
    from scripts.recovery_rag import build_task_context

    db_path = tmp_path / "recovery-rag.sqlite3"
    record_outcome(
        db_path,
        namespace="team-a",
        task_id="task-42",
        status="FAIL",
        category="timeout",
        fingerprint="f" * 64,
    )
    assert build_task_context(
        db_path,
        namespace="team-b",
        task_id="unrelated-task",
        instruction="A documentation-only task",
    ) == ""
    assert build_task_context(
        tmp_path / "missing.sqlite3",
        namespace="team-a",
        task_id="task-42",
        instruction="timeout",
    ) == ""
