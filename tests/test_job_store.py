import db
import job_store


def test_create_get_and_claim_job(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = job_store.create_job("U-test", "夜間にテスト", source="test")
    job = job_store.get_job(job_id)

    assert job["status"] == "pending"
    assert job["source"] == "test"
    assert job["retry_count"] == 0
    assert job["max_retries"] == 3

    claimed = job_store.claim_pending_job()
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert job_store.claim_pending_job() is None


def test_checkpoint_and_job_update(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = job_store.create_job("U-test", "checkpoint test")
    checkpoint_id = job_store.save_checkpoint(
        job_id, "requirements", "completed", '{"ok": true}'
    )
    assert checkpoint_id is not None

    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["job_id"] == job_id
    assert checkpoint["step_name"] == "requirements"
    assert checkpoint["step_status"] == "completed"
    assert checkpoint["output_snapshot"] == '{"ok": true}'

    assert job_store.update_job(job_id, status="done", result="success") is True
    job = job_store.get_job(job_id)
    assert job["status"] == "done"
    assert job["result"] == "success"


def test_parent_job_and_retry_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    parent_id = job_store.create_job("U-test", "parent")
    child_id = job_store.create_job(
        "U-test",
        "child",
        source="derived",
        parent_job_id=parent_id,
        max_retries=5,
    )

    child = job_store.get_job(child_id)
    assert child["parent_job_id"] == parent_id
    assert child["max_retries"] == 5


def test_idempotency_key_returns_existing_job_after_repeated_request(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    first = job_store.create_job(
        "U-test", "same request", source="line", idempotency_key="line:event-123"
    )
    second = job_store.create_job(
        "U-test", "same request", source="line", idempotency_key="line:event-123"
    )

    assert second == first
    assert job_store.get_job(first)["status"] == "pending"


def test_idempotency_key_rejects_different_request_payload(tmp_path, monkeypatch):
    import pytest

    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_store.create_job(
        "U-test", "original request", idempotency_key="line:event-456"
    )
    with pytest.raises(ValueError, match="different request"):
        job_store.create_job(
            "U-test", "different request", idempotency_key="line:event-456"
        )


def test_idempotency_key_survives_database_reopen(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()
    first = job_store.create_job(
        "U-test", "durable request", idempotency_key="line:event-789"
    )

    db.init_db()
    second = job_store.create_job(
        "U-test", "durable request", idempotency_key="line:event-789"
    )
    assert second == first


def test_idempotency_key_validation_rejects_blank_and_oversized_values(tmp_path, monkeypatch):
    import pytest

    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    with pytest.raises(ValueError, match="idempotency_key"):
        job_store.create_job("U-test", "request", idempotency_key="  ")
    with pytest.raises(ValueError, match="idempotency_key"):
        job_store.create_job("U-test", "request", idempotency_key="x" * 201)


def test_idempotency_key_serializes_concurrent_registration(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    def register(_):
        return job_store.create_job(
            "U-test", "concurrent request", idempotency_key="line:event-concurrent"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        job_ids = list(pool.map(register, range(24)))

    assert len(set(job_ids)) == 1


def test_init_db_migrates_existing_jobs_table(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                job_type TEXT NOT NULL DEFAULT 'ai_task',
                source TEXT NOT NULL DEFAULT 'line',
                parent_job_id INTEGER,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                last_error TEXT,
                result TEXT,
                claim_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO jobs(user_id, message) VALUES (?, ?)",
            ("U-legacy", "existing job"),
        )

    db.init_db()
    columns = {
        row[1]
        for row in sqlite3.connect(db_path).execute("PRAGMA table_info(jobs)").fetchall()
    }
    assert {"idempotency_key", "request_fingerprint"} <= columns

    migrated = job_store.create_job(
        "U-test", "new request", idempotency_key="line:event-after-migration"
    )
    assert migrated is not None
    assert job_store.get_job(1)["message"] == "existing job"


def test_idempotency_keys_are_scoped_per_user(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    first = job_store.create_job(
        "U-one", "request one", idempotency_key="same-client-key"
    )
    second = job_store.create_job(
        "U-two", "request two", idempotency_key="same-client-key"
    )

    assert first != second
    assert job_store.get_job(first)["user_id"] == "U-one"
    assert job_store.get_job(second)["user_id"] == "U-two"
