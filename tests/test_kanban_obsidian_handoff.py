"""Safety tests for the verified Kanban-to-Obsidian approval handoff."""
import json
import pytest
from flask import Flask

import db
from routes.obsidian_bridge import obsidian_bridge_bp

KEY = "handoff-test-key"
HEADERS = {"X-Kanban-Handoff-Key": KEY}
PAYLOAD = {
    "task_id": "task-123",
    "status": "PASS",
    "summary": "Tests passed for bounded change",
    "evidence_ref": "https://github.com/nonkun12/line-bot/actions/runs/123",
    "commit_sha": "a" * 40,
    "verification": {"tests_passed": True, "safety_gate_passed": True},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "handoff.sqlite3"))
    db.init_db()
    monkeypatch.setenv("KANBAN_OBSIDIAN_HANDOFF_KEY", KEY)
    monkeypatch.setenv("KANBAN_OBSIDIAN_USER_ID", "U-test-owner")
    app = Flask(__name__)
    app.register_blueprint(obsidian_bridge_bp)
    return app.test_client()


def test_accepts_verified_pass_into_pending_approval_queue(client):
    response = client.post("/api/obsidian/kanban-result", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 202
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == "pending_approval"
    job = db.get_job(body["job_id"])
    assert job["status"] == "pending"
    assert job["job_type"] == "obsidian"
    assert job["source"] == "kanban"
    assert "Task task-123" in job["message"]
    assert "a" * 40 in job["message"]


def test_rejects_bad_auth_and_missing_server_configuration(client, monkeypatch):
    assert client.post("/api/obsidian/kanban-result", json=PAYLOAD).status_code == 401
    monkeypatch.delenv("KANBAN_OBSIDIAN_HANDOFF_KEY")
    assert client.post("/api/obsidian/kanban-result", json=PAYLOAD, headers=HEADERS).status_code == 401
    monkeypatch.setenv("KANBAN_OBSIDIAN_HANDOFF_KEY", KEY)
    monkeypatch.delenv("KANBAN_OBSIDIAN_USER_ID")
    assert client.post("/api/obsidian/kanban-result", json=PAYLOAD, headers=HEADERS).status_code == 503


@pytest.mark.parametrize("status", ["FAIL", "BLOCKED", "DONE", "PASS_WITH_WARNINGS", None])
def test_rejects_non_pass_or_ambiguous_status(client, status):
    payload = {**PAYLOAD, "status": status}
    assert client.post("/api/obsidian/kanban-result", json=payload, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("verification", [None, {}, {"tests_passed": True}, {"safety_gate_passed": True},
                                          {"tests_passed": 1, "safety_gate_passed": True}])
def test_rejects_incomplete_verification(client, verification):
    payload = {**PAYLOAD, "verification": verification}
    assert client.post("/api/obsidian/kanban-result", json=payload, headers=HEADERS).status_code == 422


def test_rejects_malformed_or_oversized_payload(client):
    for patch in (
        {"task_id": "../bad"}, {"task_id": " "}, {"commit_sha": "not-a-sha"},
        {"evidence_ref": "http://insecure.example"}, {"summary": "x" * 501},
        {"summary": "   "}, {"evidence_ref": "x" * 301},
    ):
        payload = {**PAYLOAD, **patch}
        assert client.post("/api/obsidian/kanban-result", json=payload, headers=HEADERS).status_code == 400
    assert client.post("/api/obsidian/kanban-result", data="no-json", headers=HEADERS).status_code == 400


def test_duplicate_task_id_is_rejected_without_second_job(client):
    first = client.post("/api/obsidian/kanban-result", json=PAYLOAD, headers=HEADERS)
    second = client.post("/api/obsidian/kanban-result", json=PAYLOAD, headers=HEADERS)
    assert first.status_code == 202
    assert second.status_code == 409
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE source='kanban'").fetchone()[0] == 1


def test_payload_is_sanitized_and_fixed_vault_destination_is_used(client):
    payload = {**PAYLOAD, "summary": "done\nSECRET=value\tOK"}
    response = client.post("/api/obsidian/kanban-result", json=payload, headers=HEADERS)
    assert response.status_code == 202
    job = db.get_job(response.get_json()["job_id"])
    assert "SECRET=value" not in job["message"]
    assert "SECRET=[REDACTED]" in job["message"]
    assert "\n" not in job["message"]
    assert "LINE-Inbox.md" in job["message"]
    assert "user_id" not in json.dumps(response.get_json())
