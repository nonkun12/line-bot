from __future__ import annotations

import json
import sqlite3

import pytest

from core import collaboration_audit


def test_collaboration_snapshot_storage_is_user_scoped_and_bounded(monkeypatch, tmp_path):
    db_path = tmp_path / "audit.sqlite"
    monkeypatch.setattr(
        collaboration_audit,
        "get_conn",
        lambda: sqlite3.connect(db_path),
    )
    for index in range(23):
        collaboration_audit.record_collaboration_snapshot(
            user_id="user-a",
            snapshot={"agent_count": index, "accepted": False},
        )
    collaboration_audit.record_collaboration_snapshot(
        user_id="user-b",
        snapshot={"agent_count": 1},
    )

    rows = collaboration_audit.list_collaboration_snapshots(user_id="user-a", limit=20)
    assert len(rows) == 20
    assert rows[0]["snapshot"]["agent_count"] == 22
    assert rows[-1]["snapshot"]["agent_count"] == 3
    assert len(collaboration_audit.list_collaboration_snapshots(user_id="user-b")) == 1


def test_collaboration_snapshot_storage_rejects_oversized_or_invalid_data(monkeypatch):
    monkeypatch.setattr(
        collaboration_audit,
        "get_conn",
        lambda: (_ for _ in ()).throw(AssertionError("DB must not be touched")),
    )
    with pytest.raises(ValueError, match="user_id"):
        collaboration_audit.record_collaboration_snapshot(user_id="", snapshot={})
    with pytest.raises(ValueError, match="size limit"):
        collaboration_audit.record_collaboration_snapshot(
            user_id="user-a",
            snapshot={"finding": "x" * 17000},
        )
    with pytest.raises(ValueError, match="limit"):
        collaboration_audit.list_collaboration_snapshots(user_id="user-a", limit=21)
