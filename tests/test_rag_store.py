import json

import pytest

from rag_store import RagStore


def test_add_and_search_japanese_text(tmp_path):
    store = RagStore(tmp_path / "rag.sqlite3")
    stored = store.add_document(
        namespace="engineering",
        source="test",
        source_id="recovery-1",
        title="Recovery AI",
        content="分散Loopのキューが空になったら次のタスクを補充する。",
        metadata={"status": "verified"},
    )

    results = store.search(namespace="engineering", query="キューが空", limit=3)

    assert stored["source_id"] == "recovery-1"
    assert len(results) == 1
    assert results[0]["title"] == "Recovery AI"
    assert results[0]["metadata"] == {"status": "verified"}
    assert "キューが空" in results[0]["snippet"]


def test_upsert_is_idempotent_for_same_source(tmp_path):
    store = RagStore(tmp_path / "rag.sqlite3")
    first = store.add_document(
        namespace="engineering", source="github", source_id="issue-12",
        title="Queue refill", content="Create a bounded task when queue is empty.",
    )
    second = store.add_document(
        namespace="engineering", source="github", source_id="issue-12",
        title="Queue refill", content="Create a bounded task when queue is empty.",
    )
    assert first["id"] == second["id"]
    assert store.search(namespace="engineering", query="queue", limit=5).__len__() == 1


def test_namespace_isolation(tmp_path):
    store = RagStore(tmp_path / "rag.sqlite3")
    store.add_document(
        namespace="user-a", source="note", source_id="1",
        title="Private", content="unique blue lantern",
    )
    store.add_document(
        namespace="user-b", source="note", source_id="1",
        title="Other", content="unique blue lantern",
    )

    results = store.search(namespace="user-a", query="unique blue lantern")
    assert len(results) == 1
    assert results[0]["title"] == "Private"


@pytest.mark.parametrize("limit", [0, -1, 21, True])
def test_rejects_invalid_limit(tmp_path, limit):
    store = RagStore(tmp_path / "rag.sqlite3")
    with pytest.raises(ValueError):
        store.search(namespace="engineering", query="test", limit=limit)


def test_rejects_empty_document(tmp_path):
    store = RagStore(tmp_path / "rag.sqlite3")
    with pytest.raises(ValueError):
        store.add_document(
            namespace="engineering", source="test", source_id="empty", content="  "
        )
