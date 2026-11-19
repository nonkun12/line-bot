import db
import job_store
import job_worker


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_run_once_dry_run_completes_job(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "worker test")

    result = job_worker.run_once()

    assert result["id"] == job_id
    assert result["status"] == "done"
    assert result["result"] == "dry_run"
    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_name"] == "worker"
    assert checkpoint["step_status"] == "completed"


def test_run_once_uses_injected_executor(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "executor test")

    def executor(job):
        assert job["id"] == job_id
        return "executed"

    result = job_worker.run_once(executor=executor)
    assert result["status"] == "done"
    assert result["result"] == "executed"


def test_run_once_records_failure(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "failure test")

    def executor(_job):
        raise RuntimeError("expected failure")

    result = job_worker.run_once(executor=executor)
    assert result["id"] == job_id
    assert result["status"] == "failed"
    assert result["last_error"] == "expected failure"
    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_status"] == "failed"


def test_run_once_returns_none_without_pending_job(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    assert job_worker.run_once() is None
