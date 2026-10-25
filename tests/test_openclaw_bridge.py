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
        headers={"X-OpenClaw-Bridge-Key": "secret"},
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
        headers={"X-OpenClaw-Bridge-Key": "secret"},
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
        headers={"X-OpenClaw-Bridge-Key": "secret"},
    )
    assert response.status_code == 409


def test_complete_rejects_non_boolean_success(monkeypatch):
    monkeypatch.setenv("OPENCLAW_BRIDGE_KEY", "s" * 32)
    response = make_app().test_client().post(
        "/api/openclaw/complete",
        json={"job_id": 4, "claim_token": "opaque", "success": "yes"},
        headers={"X-OpenClaw-Bridge-Key": "secret"},
    )
    assert response.status_code == 400
