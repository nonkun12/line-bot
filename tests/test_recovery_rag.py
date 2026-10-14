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
