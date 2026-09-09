import db
import job_store


def test_expired_worker_cannot_renew_or_update(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()

    job_id = db.create_job("Utest", "lease", job_type="development")
    claimed = db.claim_pending_job("worker-a", lease_seconds=60)
    assert claimed["id"] == job_id

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET lease_until=datetime('now', '-1 seconds') WHERE id=?",
            (job_id,),
        )

    assert db.renew_job_lease(job_id, "worker-a", lease_seconds=60) is False
    assert job_store.update_job_owned(
        job_id,
        "worker-a",
        status="pending",
        result="stale worker must be fenced",
        clear_lease=True,
    ) is False

    current = db.get_job(job_id)
    assert current["status"] == "running"
    assert current["worker_id"] == "worker-a"
