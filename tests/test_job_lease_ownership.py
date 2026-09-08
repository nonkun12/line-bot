import db
import job_store
from job_lease import recover_stale_jobs


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()
    return db_path


def test_only_current_worker_can_update_running_job(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    job_id = db.create_job("user-1", "test", job_type="development")

    claimed = job_store.claim_pending_job(worker_id="worker-a", lease_seconds=60)
    assert claimed["id"] == job_id
    assert claimed["worker_id"] == "worker-a"

    assert job_store.update_job_owned(
        job_id,
        "worker-a",
        result="owned update",
    ) is True
    assert job_store.update_job_owned(
        job_id,
        "worker-b",
        result="stale update",
    ) is False

    current = job_store.get_job(job_id)
    assert current["result"] == "owned update"
    assert current["worker_id"] == "worker-a"
    assert current["status"] == "running"


def test_stale_recovery_clears_lease_and_blocks_old_worker(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    job_id = db.create_job("user-1", "test", job_type="development")

    claimed = job_store.claim_pending_job(worker_id="worker-a", lease_seconds=1)
    assert claimed["id"] == job_id

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET lease_until=datetime('now', '-10 seconds') WHERE id=?",
            (job_id,),
        )

    recovered = recover_stale_jobs(stale_seconds=1)
    assert recovered == [job_id]

    current = job_store.get_job(job_id)
    assert current["status"] == "pending"
    assert current["worker_id"] is None
    assert current["lease_until"] is None

    assert job_store.update_job_owned(
        job_id,
        "worker-a",
        status="done",
        result="stale worker must not win",
        clear_lease=True,
    ) is False

    current = job_store.get_job(job_id)
    assert current["status"] == "pending"
    assert current["result"] is None
