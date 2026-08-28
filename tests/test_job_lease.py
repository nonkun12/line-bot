import sqlite3
from datetime import datetime, timedelta, timezone

import db
import job_lease


def test_recover_stale_running_job(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = db.create_job("U-test", "stale")
    db.claim_pending_job()

    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db.DB) as conn:
        conn.execute(
            "UPDATE jobs SET updated_at=?, status='running' WHERE id=?",
            (stale, job_id),
        )

    recovered = job_lease.recover_stale_jobs(stale_seconds=60)

    assert recovered == [job_id]
    job = db.get_job(job_id)
    assert job["status"] == "pending"
    checkpoint = db.get_latest_checkpoint(job_id)
    assert checkpoint["step_name"] == "worker_recovery"
    assert checkpoint["step_status"] == "stalled"
