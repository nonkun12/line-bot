import db
import job_approvals


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(db, "DB", str(db_path))
    db.init_db()


def test_job_operation_is_scoped(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_a = db.create_job("U-a", "a")
    job_b = db.create_job("U-b", "b")
    job_approvals.request(job_a, "U-a", "commit")
    job_approvals.request(job_b, "U-b", "commit")

    assert job_approvals.approve(job_a, "commit", "human") is True
    assert job_approvals.status(job_a, "commit") == "approved"
    assert job_approvals.status(job_b, "commit") == "pending"


def test_commit_and_deploy_are_independent(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "approval")
    job_approvals.request(job_id, "U-test", "commit")
    job_approvals.request(job_id, "U-test", "deploy")
    assert job_approvals.approve(job_id, "commit", "human") is True
    assert job_approvals.status(job_id, "commit") == "approved"
    assert job_approvals.status(job_id, "deploy") == "pending"


def test_approval_is_one_use(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "approval")
    job_approvals.request(job_id, "U-test", "commit")
    job_approvals.approve(job_id, "commit", "human")

    assert job_approvals.consume(job_id, "commit") is True
    assert job_approvals.status(job_id, "commit") == "consumed"
    assert job_approvals.consume(job_id, "commit") is False


def test_reject_blocks_operation(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "reject")
    job_approvals.request(job_id, "U-test", "deploy")
    assert job_approvals.reject(job_id, "deploy") is True
    assert job_approvals.status(job_id, "deploy") == "rejected"


def test_expired_blocks_operation(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    job_id = db.create_job("U-test", "expire")
    job_approvals.request(
        job_id,
        "U-test",
        "deploy",
        expires_at="2000-01-01T00:00:00+00:00",
    )
    assert job_approvals.status(job_id, "deploy") == "expired"
