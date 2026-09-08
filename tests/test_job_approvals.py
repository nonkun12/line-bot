import db
import job_approvals
import job_store


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_approve_requeues_waiting_job(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "deploy", max_retries=3)
    job_store.update_job(job_id, status="waiting_approval")

    record = job_approvals.request(job_id, "U-test", "deploy")
    assert record["status"] == "pending"

    assert job_approvals.approve(job_id, "deploy", "U-test") is True
    assert job_approvals.status(job_id, "deploy") == "approved"
    assert job_store.get_job(job_id)["status"] == "pending"


def test_reject_terminates_waiting_job(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "commit")
    job_store.update_job(job_id, status="waiting_approval")
    job_approvals.request(job_id, "U-test", "commit")

    assert job_approvals.reject(job_id, "commit") is True
    job = job_store.get_job(job_id)
    assert job["status"] == "failed"
    assert "commit approval rejected" in job["last_error"]


def test_worker_denied_approval_is_terminal(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = job_store.create_job("U-test", "commit")
    job_store.update_job(job_id, status="waiting_approval")
    job_approvals.request(job_id, "U-test", "commit")
    assert job_approvals.reject(job_id, "commit") is True

    import job_worker

    class Snapshot:
        values = {"request_id": f"job-{job_id}"}
        next = ("merge_agent",)

    class Graph:
        def get_state(self, _config):
            return Snapshot()

    result = job_worker.execute_one_step(job_store.get_job(job_id), graph=Graph())
    assert result["status"] == "failed"
    assert "approval rejected" in result["error"]
