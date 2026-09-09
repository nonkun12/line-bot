from datetime import datetime, timezone

import db
import job_approvals


def test_job_approval_gets_default_expiration(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()
    job_id = db.create_job("Utest", "approval test", job_type="development")

    approval = job_approvals.request(job_id, "Utest", "commit")

    assert approval["status"] == "pending"
    assert approval["expires_at"]
    expires = datetime.fromisoformat(str(approval["expires_at"]))
    assert expires.tzinfo is not None
    assert expires > datetime.now(timezone.utc)


def test_job_approval_expiration_can_be_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.db"))
    db.init_db()
    job_id = db.create_job("Utest", "approval test", job_type="development")
    expires_at = "2099-01-01T00:00:00+00:00"

    approval = job_approvals.request(job_id, "Utest", "deploy", expires_at=expires_at)

    assert approval["expires_at"] == expires_at
