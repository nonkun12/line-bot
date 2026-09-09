import db
import job_store


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_create_get_and_claim_job(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)

    job_id = job_store.create_job("U-test", "夜間にテスト", source="test")
    job = job_store.get_job(job_id)

    assert job["status"] == "pending"
    assert job["source"] == "test"
    assert job["retry_count"] == 0
    assert job["max_retries"] == 3

    claimed = job_store.claim_pending_job(worker_id="worker-a", lease_seconds=60)
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["worker_id"] == "worker-a"
    assert claimed["lease_until"]
    assert job_store.claim_pending_job(worker_id="worker-b", lease_seconds=60) is None


def test_renew_job_lease_requires_owner(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "lease test")
    claimed = job_store.claim_pending_job(worker_id="worker-a", lease_seconds=60)

    assert claimed["id"] == job_id
    assert job_store.renew_job_lease(job_id, "worker-b", lease_seconds=60) is False
    assert job_store.renew_job_lease(job_id, "worker-a", lease_seconds=120) is True

    renewed = job_store.get_job(job_id)
    assert renewed["worker_id"] == "worker-a"
    assert renewed["lease_until"]


def test_update_clears_worker_lease(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "clear lease")
    job_store.claim_pending_job(worker_id="worker-a", lease_seconds=60)

    assert job_store.update_job(job_id, status="pending", clear_claimed_at=True) is True
    job = job_store.get_job(job_id)
    assert job["status"] == "pending"
    assert job["worker_id"] is None
    assert job["lease_until"] is None


def test_checkpoint_and_job_update(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)

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
    setup_db(tmp_path, monkeypatch)

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
