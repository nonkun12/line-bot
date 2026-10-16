import json
import sqlite3

import pytest
import db

from core.local_review_jobs import (
    REVIEW_JOB_TYPE,
    build_review_payload,
    enqueue_local_review,
)


BASE = "a" * 40
HEAD = "b" * 40


def test_payload_contains_only_allowlisted_review_metadata():
    payload = json.loads(build_review_payload("nonkun12/line-bot", BASE, HEAD))
    assert payload == {
        "schema_version": 1,
        "kind": REVIEW_JOB_TYPE,
        "repository": "nonkun12/line-bot",
        "base_sha": BASE,
        "head_sha": HEAD,
    }
    assert "command" not in payload
    assert "path" not in payload


@pytest.mark.parametrize(
    ("repository", "base", "head"),
    [
        ("other/repo", BASE, HEAD),
        ("nonkun12/line-bot", "short", HEAD),
        ("nonkun12/line-bot", BASE.upper(), HEAD),
        ("nonkun12/line-bot", BASE, BASE),
    ],
)
def test_payload_rejects_invalid_or_untrusted_inputs(repository, base, head):
    with pytest.raises(ValueError):
        build_review_payload(repository, base, head)


def _memory_jobs_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            source TEXT NOT NULL,
            parent_job_id INTEGER,
            message TEXT NOT NULL,
            status TEXT NOT NULL,
            max_retries INTEGER NOT NULL
        )
    """)
    return conn


def test_enqueue_creates_dedicated_job_and_deduplicates_active_request(monkeypatch):
    conn = _memory_jobs_db()
    monkeypatch.setattr("core.local_review_jobs.get_conn", lambda: conn)

    first = enqueue_local_review("U1", "nonkun12/line-bot", BASE, HEAD)
    second = enqueue_local_review("U1", "nonkun12/line-bot", BASE, HEAD)

    assert first == second
    rows = conn.execute(
        "SELECT user_id, job_type, source, max_retries, status FROM jobs"
    ).fetchall()
    assert rows == [("U1", REVIEW_JOB_TYPE, "control_tower", 1, "pending")]


def test_enqueue_allows_new_job_after_previous_job_is_terminal(monkeypatch):
    conn = _memory_jobs_db()
    monkeypatch.setattr("core.local_review_jobs.get_conn", lambda: conn)
    first = enqueue_local_review("U1", "nonkun12/line-bot", BASE, HEAD)
    conn.execute("UPDATE jobs SET status='failed' WHERE id=?", (first,))
    conn.commit()
    second = enqueue_local_review("U1", "nonkun12/line-bot", BASE, HEAD)
    assert second != first
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_enqueue_rejects_missing_user(monkeypatch):
    def unexpected_create_job(*args, **kwargs):
        raise AssertionError("must reject before touching DB")

    monkeypatch.setattr("core.local_review_jobs.create_job", unexpected_create_job)
    with pytest.raises(ValueError, match="user_id"):
        enqueue_local_review("", "nonkun12/line-bot", BASE, HEAD)



def test_stale_job_at_retry_limit_becomes_terminal_failed(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            source TEXT NOT NULL,
            parent_job_id INTEGER,
            message TEXT NOT NULL,
            status TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 1,
            last_error TEXT,
            result TEXT,
            claim_token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    payload = build_review_payload("nonkun12/line-bot", BASE, HEAD)
    conn.execute(
        """INSERT INTO jobs(user_id,job_type,source,message,status,retry_count,
           max_retries,claim_token,updated_at)
           VALUES(?,?,?,?, 'running', 1, 1, 'stale-token', datetime('now','-1 day'))""",
        ("U1", REVIEW_JOB_TYPE, "control_tower", payload),
    )
    conn.commit()
    monkeypatch.setattr(db, "get_conn", lambda: conn)

    claimed = db.claim_pending_job_by_type(REVIEW_JOB_TYPE, stale_after_seconds=900)

    assert claimed is None
    row = conn.execute(
        "SELECT status, claim_token, last_error FROM jobs WHERE id=1"
    ).fetchone()
    assert row == ("failed", None, "stale job exceeded retry limit")
