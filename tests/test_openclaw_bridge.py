from __future__ import annotations

import pytest
from flask import Flask

import core.openclaw_bridge as core
import routes.openclaw_bridge as routes


def make_app():
    app = Flask(__name__)
    app.register_blueprint(routes.openclaw_bridge_bp)
    return app


def test_intent_requires_explicit_prefix():
    assert core.is_openclaw_intent("OpenClaw: inspect the repo")
    assert core.is_openclaw_intent("OpenClawでテストを確認")
    assert not core.is_openclaw_intent("inspect the repo")


def test_normalize_rejects_empty_and_oversized():
    with pytest.raises(core.OpenClawBridgeError):
        core.normalize_openclaw_message("OpenClaw:")
    with pytest.raises(core.OpenClawBridgeError):
        core.normalize_openclaw_message("OpenClaw: " + "x" * 4001)


def test_enqueue_requires_bridge_key(monkeypatch):
    monkeypatch.delenv("OPENCLAW_BRIDGE_KEY", raising=False)
    with pytest.raises(core.OpenClawBridgeError):
        core.enqueue_openclaw_request("U1", "OpenClaw: run tests")


def test_enqueue_rejects_short_bridge_key(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "too-short")
    with pytest.raises(core.OpenClawBridgeError):
        core.enqueue_openclaw_request("U1", "OpenClaw: run tests")


def test_enqueue_creates_typed_job(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "x" * 32)
    calls = {}
    def fake_create_job(user_id, message, **kwargs):
        calls.update(user_id=user_id, message=message, **kwargs)
        return 12
    monkeypatch.setattr(core, "create_job", fake_create_job)
    assert core.enqueue_openclaw_request("U1", "OpenClaw: run tests") == 12
    assert calls == {
        "user_id": "U1", "message": "run tests", "job_type": "openclaw",
        "source": "line", "max_retries": 3,
    }


def test_status_requires_auth_and_does_not_read_queue_without_it(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    monkeypatch.setattr(
        routes, "_read_queue_summary",
        lambda: pytest.fail("unauthenticated status must not inspect the queue"),
    )
    response = make_app().test_client().get("/api/openclaw/status")
    assert response.status_code == 401


def test_status_returns_only_read_only_queue_counts(monkeypatch, tmp_path):
    import db

    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    database = tmp_path / "jobs.sqlite3"
    monkeypatch.setattr(db, "DB", str(database))
    db.init_db()
    pending_id = db.create_job(
        "U1", "private task text", job_type="openclaw", max_retries=3
    )
    running_id = db.create_job(
        "U2", "another private task", job_type="openclaw", max_retries=3
    )
    db.update_job(running_id, status="running")
    db.create_job("U3", "unrelated", job_type="ai_task")
    monkeypatch.setattr(routes, "DB", str(database))

    response = make_app().test_client().get(
        "/api/openclaw/status",
        headers={"X-OpenClaw-Bridge-Key": "s" * 32},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "queue": {"pending": 1, "running": 1, "completed": 0, "failed": 0},
    }
    assert pending_id > 0
    assert db.get_job(pending_id)["status"] == "pending"
    assert db.get_job(running_id)["status"] == "running"
    # The endpoint returns no task text, user IDs, claim tokens, or job IDs.


def test_claim_requires_auth(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    response = make_app().test_client().post("/api/openclaw/claim", json={})
    assert response.status_code == 401


def test_claim_rejects_weak_server_key(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "weak")
    response = make_app().test_client().post(
        "/api/openclaw/claim", json={},
        headers={"X-OpenClaw-Bridge-Key": "weak"},
    )
    assert response.status_code == 401


def test_claim_returns_bounded_job(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    monkeypatch.setattr(routes, "claim_pending_job_by_type", lambda kind: {
        "id": 4, "user_id": "U1", "message": "run tests", "claim_token": "opaque",
        "internal_field": "must not leak",
    })
    response = make_app().test_client().post(
        "/api/openclaw/claim", json={},
        headers={"X-OpenClaw-Bridge-Key": "s" * 32},
    )
    assert response.status_code == 200
    assert response.get_json()["job"] == {
        "id": 4, "user_id": "U1", "message": "run tests", "claim_token": "opaque",
    }


def test_complete_rejects_wrong_job_type(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    monkeypatch.setattr(routes, "get_job", lambda job_id: {"job_type": "obsidian", "status": "running"})
    response = make_app().test_client().post(
        "/api/openclaw/complete",
        json={"job_id": 4, "claim_token": "opaque", "success": True},
        headers={"X-OpenClaw-Bridge-Key": "s" * 32},
    )
    assert response.status_code == 404


def test_complete_rejects_claim_mismatch(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    monkeypatch.setattr(routes, "get_job", lambda job_id: {
        "job_type": "openclaw", "status": "running", "claim_token": "different",
    })
    response = make_app().test_client().post(
        "/api/openclaw/complete",
        json={"job_id": 4, "claim_token": "opaque", "success": True},
        headers={"X-OpenClaw-Bridge-Key": "s" * 32},
    )
    assert response.status_code == 409


def test_complete_rejects_non_boolean_success(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    response = make_app().test_client().post(
        "/api/openclaw/complete",
        json={"job_id": 4, "claim_token": "opaque", "success": "yes"},
        headers={"X-OpenClaw-Bridge-Key": "s" * 32},
    )
    assert response.status_code == 400


def test_complete_failure_notifies_line_without_leaking_error(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    monkeypatch.setattr(routes, "get_job", lambda job_id: {
        "job_type": "openclaw", "status": "running", "claim_token": "opaque", "user_id": "U1",
    })
    monkeypatch.setattr(routes, "complete_claimed_job", lambda *a, **kw: True)
    import app as app_module
    pushed = []
    monkeypatch.setattr(app_module, "_line_push", lambda user_id, message: pushed.append((user_id, message)))
    response = make_app().test_client().post(
        "/api/openclaw/complete",
        json={"job_id": 4, "claim_token": "opaque", "success": False,
              "error": "secret local path /Users/private/config"},
        headers={"X-OpenClaw-Bridge-Key": "s" * 32},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "failed"
    assert pushed == [("U1", "OpenClawの処理に失敗しました。時間をおいて再試行してください。")]
    assert "private" not in pushed[0][1]


def test_openclaw_prefix_routes_to_authenticated_mac_queue(monkeypatch):
    from types import SimpleNamespace
    import app as app_module

    queued = []
    monkeypatch.setattr(
        app_module, "enqueue_openclaw_request",
        lambda user_id, message: queued.append((user_id, message)) or 12,
    )
    monkeypatch.setattr(
        app_module, "generate_reply",
        lambda *a, **kw: pytest.fail("explicit OpenClaw requests must use the Mac queue"),
    )

    response = app_module._handle_ai_gateway_request(
        SimpleNamespace(message="OpenClaw: explain this", user_id="U-test")
    )

    assert queued == [("U-test", "OpenClaw: explain this")]
    assert "Job 12" in response
    assert "Bonsaiワーカー" in response


def test_openclaw_enqueue_failure_fails_closed(monkeypatch):
    from types import SimpleNamespace
    import app as app_module

    monkeypatch.setattr(
        app_module, "enqueue_openclaw_request",
        lambda *a, **kw: (_ for _ in ()).throw(core.OpenClawBridgeError("missing key")),
    )
    monkeypatch.setattr(
        app_module, "generate_reply",
        lambda *a, **kw: pytest.fail("must not fall through to cloud AI"),
    )

    response = app_module._handle_ai_gateway_request(
        SimpleNamespace(message="OpenClaw: run tests", user_id="U-test")
    )

    assert "受け付けられませんでした" in response


def test_stale_job_at_retry_limit_becomes_failed(monkeypatch, tmp_path):
    import db

    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.sqlite3"))
    db.init_db()
    job_id = db.create_job(
        "U1", "run tests", job_type="openclaw", max_retries=3
    )
    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status='running', retry_count=3, claim_token='stale-token',
                updated_at=datetime('now', '-1 hour')
            WHERE id=?
            """,
            (job_id,),
        )

    assert db.claim_pending_job_by_type("openclaw", stale_after_seconds=60) is None
    job = db.get_job(job_id)
    assert job["status"] == "failed"
    assert job["retry_count"] == 3
    assert job["claim_token"] is None
    assert job["last_error"] == "worker claim timed out after maximum retries"


def test_stale_job_with_retry_budget_is_requeued_and_claimed(monkeypatch, tmp_path):
    import db

    monkeypatch.setattr(db, "DB", str(tmp_path / "jobs.sqlite3"))
    db.init_db()
    job_id = db.create_job(
        "U1", "run tests", job_type="openclaw", max_retries=3
    )
    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status='running', retry_count=1, claim_token='stale-token',
                updated_at=datetime('now', '-1 hour')
            WHERE id=?
            """,
            (job_id,),
        )

    claimed = db.claim_pending_job_by_type("openclaw", stale_after_seconds=60)
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["retry_count"] == 2
    assert claimed["claim_token"]


def test_auth_rejection_logs_only_short_key_fingerprints(monkeypatch, caplog):
    import hashlib

    expected = "expected-secret-" + "e" * 32
    provided = "provided-secret-" + "p" * 32
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", expected)

    response = make_app().test_client().get(
        "/api/openclaw/status",
        headers={"X-OpenClaw-Bridge-Key": provided},
    )

    assert response.status_code == 401
    log_text = " ".join(record.getMessage() for record in caplog.records)
    expected_fp = hashlib.sha256(expected.encode("utf-8")).hexdigest()[:16]
    provided_fp = hashlib.sha256(provided.encode("utf-8")).hexdigest()[:16]
    assert f"expected_fp={expected_fp}" in log_text
    assert f"provided_fp={provided_fp}" in log_text
    assert expected not in log_text
    assert provided not in log_text
