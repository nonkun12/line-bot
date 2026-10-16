import json

import pytest
from flask import Flask

from core.local_review_jobs import REVIEW_JOB_TYPE, build_review_payload
from routes import local_review_bridge as bridge


KEY = "test-local-review-key"
BASE = "a" * 40
HEAD = "b" * 40


@pytest.fixture()
def client(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(bridge.local_review_bridge_bp)
    app.config["TESTING"] = True
    monkeypatch.setenv("LOCAL_REVIEW_BRIDGE_KEY", KEY)
    return app.test_client()


def auth():
    return {"X-Local-Review-Bridge-Key": KEY}


def running_job(job_type=REVIEW_JOB_TYPE, message=None, token="claim-secret"):
    return {
        "id": 23,
        "user_id": "U-test",
        "job_type": job_type,
        "message": message or build_review_payload("nonkun12/line-bot", BASE, HEAD),
        "status": "running",
        "claim_token": token,
    }


def test_pending_requires_auth(client):
    response = client.get("/api/local-review/pending")
    assert response.status_code == 401


def test_claim_uses_only_review_job_type(client, monkeypatch):
    calls = []

    def fake_claim(job_type, *, stale_after_seconds):
        calls.append((job_type, stale_after_seconds))
        return None

    monkeypatch.setattr(bridge, "claim_pending_job_by_type", fake_claim)
    response = client.post("/api/local-review/claim", headers=auth())
    assert response.status_code == 200
    assert response.json == {"ok": True, "job": None}
    assert calls == [(REVIEW_JOB_TYPE, 900)]


def test_claim_rejects_malformed_payload_without_returning_it(client, monkeypatch):
    monkeypatch.setattr(bridge, "claim_pending_job_by_type", lambda *a, **k: running_job(message='{"kind":"obsidian"}'))
    completed = []
    monkeypatch.setattr(bridge, "complete_claimed_job", lambda *a, **k: completed.append((a, k)) or True)
    response = client.post("/api/local-review/claim", headers=auth())
    assert response.status_code == 422
    assert "obsidian" not in response.get_data(as_text=True)
    assert completed and completed[0][0][0:2] == (23, "claim-secret")
    assert completed[0][1]["success"] is False


@pytest.mark.parametrize("wrong_type", ["obsidian", "ai_task", ""])
def test_complete_refuses_other_job_types(client, monkeypatch, wrong_type):
    monkeypatch.setattr(bridge, "get_job", lambda job_id: running_job(job_type=wrong_type))
    response = client.post(
        "/api/local-review/complete",
        headers=auth(),
        json={"job_id": 23, "claim_token": "claim-secret", "status": "NOT_RUN", "reason": "offline"},
    )
    assert response.status_code == 404


def test_complete_rejects_stale_or_mismatched_sha(client, monkeypatch):
    monkeypatch.setattr(bridge, "get_job", lambda job_id: running_job())
    report = {
        "schema_version": 1, "status": "REVIEWED", "provider": "local-fm",
        "base": "c" * 40, "head": HEAD, "verdict": "PASS",
        "summary": "No high risks found", "findings": [],
    }
    response = client.post(
        "/api/local-review/complete",
        headers=auth(),
        json={"job_id": 23, "claim_token": "claim-secret", "status": "REVIEWED", "report": report},
    )
    assert response.status_code == 409
    assert response.json["error"] == "report SHA mismatch"


def test_complete_rejects_invalid_json_result_and_pass_with_high_finding(client, monkeypatch):
    monkeypatch.setattr(bridge, "get_job", lambda job_id: running_job())
    report = {
        "schema_version": 1, "status": "REVIEWED", "provider": "local-fm",
        "base": BASE, "head": HEAD, "verdict": "PASS", "summary": "Looks fine",
        "findings": [{
            "severity": "high", "file": "x.py", "issue": "bug",
            "evidence": "users[user_id]", "recommendation": "validate key",
        }],
    }
    response = client.post(
        "/api/local-review/complete",
        headers=auth(),
        json={"job_id": 23, "claim_token": "claim-secret", "status": "REVIEWED", "report": report},
    )
    assert response.status_code == 400
    assert "conflicts" in response.json["error"]


def test_complete_requires_exact_claim_token(client, monkeypatch):
    monkeypatch.setattr(bridge, "get_job", lambda job_id: running_job())
    monkeypatch.setattr(bridge, "complete_claimed_job", lambda *a, **k: False)
    response = client.post(
        "/api/local-review/complete",
        headers=auth(),
        json={"job_id": 23, "claim_token": "replayed-or-wrong", "status": "NOT_RUN", "reason": "fm unavailable"},
    )
    assert response.status_code == 409
    assert response.json["error"] == "claim token rejected"


def test_not_run_completes_as_failure_not_success(client, monkeypatch):
    monkeypatch.setattr(bridge, "get_job", lambda job_id: running_job())
    captured = {}

    def fake_complete(job_id, token, **kwargs):
        captured.update(job_id=job_id, token=token, **kwargs)
        return True

    monkeypatch.setattr(bridge, "complete_claimed_job", fake_complete)
    response = client.post(
        "/api/local-review/complete",
        headers=auth(),
        json={"job_id": 23, "claim_token": "claim-secret", "status": "NOT_RUN", "reason": "fm timeout"},
    )
    assert response.status_code == 200
    assert captured["success"] is False
    stored = json.loads(captured["result"])
    assert stored["status"] == "NOT_RUN"
    assert stored["base_sha"] == BASE
    assert stored["head_sha"] == HEAD


def test_complete_rejects_unhashable_status_without_server_error(client):
    response = client.post(
        "/api/local-review/complete",
        headers=auth(),
        json={"job_id": 23, "claim_token": "claim-secret", "status": [], "reason": "bad type"},
    )
    assert response.status_code == 400
