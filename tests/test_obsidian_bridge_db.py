def test_obsidian_job_claim_and_completion(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()

    job_id = db.create_job(
        "U1",
        "Obsidianに保存 notes/todo.md: hello",
        job_type="obsidian",
        source="line",
        max_retries=3,
    )
    job = db.claim_pending_job_by_type("obsidian")

    assert job is not None
    assert job["id"] == job_id
    assert job["status"] == "running"
    assert isinstance(job["claim_token"], str)
    assert len(job["claim_token"]) >= 20

    assert db.claim_pending_job_by_type("obsidian") is None
    assert db.complete_claimed_job(
        job_id,
        job["claim_token"],
        success=True,
        result="done",
    )

    completed = db.get_job(job_id)
    assert completed["status"] == "completed"
    assert completed["result"] == "done"
    assert completed["claim_token"] is None


def test_obsidian_completion_rejects_wrong_claim_token(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()

    job_id = db.create_job(
        "U1",
        "Obsidian一覧",
        job_type="obsidian",
        source="line",
    )
    job = db.claim_pending_job_by_type("obsidian")

    assert job is not None
    assert not db.complete_claimed_job(
        job_id,
        "wrong-token",
        success=True,
        result="should not complete",
    )
    still_running = db.get_job(job_id)
    assert still_running["status"] == "running"


def test_existing_jobs_db_is_migrated_with_claim_token(tmp_path, monkeypatch):
    import sqlite3
    import db

    database = tmp_path / "jobs.db"
    monkeypatch.setattr(db, "DB", str(database))

    with sqlite3.connect(database) as conn:
        conn.execute(
            """
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    db.init_db()

    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}

    assert "claim_token" in columns
