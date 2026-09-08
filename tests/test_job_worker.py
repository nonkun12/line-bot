import db
import job_store
import job_worker


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_run_once_uses_injected_executor_and_requeues_step(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "executor test")

    def executor(job):
        assert job["id"] == job_id
        return {
            "status": "step_completed",
            "step_name": "test_agent",
            "next_step": "debug_agent",
            "summary": "step completed",
        }

    result = job_worker.run_once(executor=executor)
    assert result["id"] == job_id
    assert result["status"] == "pending"
    assert result["result"] == "step completed"
    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_name"] == "test_agent"
    assert checkpoint["step_status"] == "completed"


def test_run_once_records_test_failure_and_consumes_retry(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "failure test", max_retries=2)

    def executor(_job):
        return {
            "status": "test_failed",
            "step_name": "test_agent",
            "next_step": "debug_agent",
            "test_result": {"passed": False, "summary": "expected failure"},
            "summary": "test failed",
        }

    result = job_worker.run_once(executor=executor)
    assert result["id"] == job_id
    assert result["status"] == "pending"
    assert result["retry_count"] == 1
    assert "retry" in result["last_error"]

    checkpoint = job_store.get_latest_checkpoint(job_id)
    assert checkpoint["step_name"] == "test_agent"
    assert checkpoint["step_status"] == "test_retry_scheduled"


def test_run_once_exhausts_executor_retries(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "failure test", max_retries=1)

    def executor(_job):
        raise RuntimeError("expected failure")

    first = job_worker.run_once(executor=executor)
    assert first["status"] == "pending"
    assert first["retry_count"] == 1

    second = job_worker.run_once(executor=executor)
    assert second["id"] == job_id
    assert second["status"] == "failed"
    assert second["retry_count"] == 2
    assert "retry limit reached" in second["last_error"]


def test_run_once_returns_none_without_pending_job(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    assert job_worker.run_once() is None
