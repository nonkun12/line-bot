import db
import job_lease
import job_store


def test_recover_stale_job_clears_worker_lease(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = job_store.create_job("U-test", "stale job")
    claimed = job_store.claim_pending_job(worker_id="worker-a", lease_seconds=1)
    assert claimed["id"] == job_id
    assert claimed["worker_id"] == "worker-a"

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET lease_until=datetime('now', '-10 seconds') WHERE id=?",
            (job_id,),
        )

    recovered = job_lease.recover_stale_jobs(stale_seconds=60)
    assert recovered == [job_id]

    job = job_store.get_job(job_id)
    assert job["status"] == "pending"
    assert job["worker_id"] is None
    assert job["lease_until"] is None
    assert job["last_error"] == "worker lease expired; job requeued"

    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_name"] == "worker_recovery"
    assert checkpoint["step_status"] == "stalled"


def test_active_worker_lease_is_not_recovered(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()

    job_id = job_store.create_job("U-test", "active job")
    claimed = job_store.claim_pending_job(worker_id="worker-a", lease_seconds=300)
    assert claimed["id"] == job_id

    assert job_lease.recover_stale_jobs(stale_seconds=60) == []
    job = job_store.get_job(job_id)
    assert job["status"] == "running"
    assert job["worker_id"] == "worker-a"
