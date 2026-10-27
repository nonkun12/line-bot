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


def test_openclaw_prefix_routes_to_server_ai_without_mac_queue(monkeypatch):
    from types import SimpleNamespace
    import app as app_module

    monkeypatch.setattr(app_module, "request_recovery_resume_review", lambda *a: (False, None))
    monkeypatch.setattr(app_module, "request_distributed_loop", lambda *a: (False, None))
    monkeypatch.setattr(app_module, "is_control_tower_status_command", lambda *a: False)
    monkeypatch.setattr(app_module, "handle_core_image_command", lambda *a: None)
    monkeypatch.setattr(app_module, "is_obsidian_intent", lambda *a: False)
    monkeypatch.setattr(app_module, "extract_app_development_request", lambda *a: None)
    monkeypatch.setattr(app_module, "handle_self_introduction", lambda *a: None)
    monkeypatch.setattr(app_module, "extract_development_instruction", lambda *a: None)
    monkeypatch.setattr(app_module, "_core_dynamic_enabled", lambda: False)
    received = []
    monkeypatch.setattr(
        app_module, "generate_reply",
        lambda user_id, message: received.append((user_id, message)) or "server reply",
    )
    monkeypatch.setattr(
        app_module, "enqueue_openclaw_request",
        lambda *a, **kw: pytest.fail("Mac queue must not be used"),
        raising=False,
    )

    response = app_module._handle_ai_gateway_request(
        SimpleNamespace(message="OpenClaw: explain this", user_id="U-test")
    )

    assert response == "server reply"
    assert received == [("U-test", "explain this")]
