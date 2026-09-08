import db
from development_jobs import enqueue_development_job, is_development_request


def test_development_request_detection():
    assert is_development_request("簡単なTodoアプリを作って")
    assert not is_development_request("明日の10時にテストするとメモして")


def test_enqueue_development_job(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()
    job = enqueue_development_job("Utest", "簡単なTodoアプリを作って")
    row = db.get_job(job["job_id"])
    assert row["status"] == "pending"
    assert row["job_type"] == "development"
    assert row["message"] == "簡単なTodoアプリを作って"
