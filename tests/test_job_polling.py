import db
import job_store


def test_claim_skips_job_until_next_run_at(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()
    job_id = db.create_job("Utest", "review wait", job_type="development")
    db.update_job(job_id, next_run_at="2999-01-01 00:00:00")
    assert job_store.claim_pending_job(worker_id="worker-1") is None


def test_review_pending_update_sets_deferred_poll(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()
    job_id = db.create_job("Utest", "review wait", job_type="development")
    claimed = db.claim_pending_job(worker_id="worker-1", lease_seconds=60)
    assert claimed and claimed["id"] == job_id

    result = '{"review_result": {"status": "pending", "reason": "required GitHub review checks are still running"}}'
    assert job_store.update_job_owned(
        job_id,
        "worker-1",
        status="pending",
        result=result,
        clear_lease=True,
    )
    job = db.get_job(job_id)
    assert job["next_run_at"] is not None
    assert job_store.claim_pending_job(worker_id="worker-2") is None
