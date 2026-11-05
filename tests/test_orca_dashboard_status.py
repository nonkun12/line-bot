import hashlib
import hmac
import json
import sqlite3

import pytest
from flask import Flask

import routes.dashboard as dashboard


@pytest.fixture
def orca_client(tmp_path, monkeypatch):
    db_path = tmp_path / "orca-status.sqlite"

    def get_conn():
        return sqlite3.connect(db_path)

    monkeypatch.setattr(dashboard, "get_conn", get_conn)
    monkeypatch.setenv("ORCA_STATUS_SECRET", "test-orca-secret")
    monkeypatch.setenv("DASHBOARD_USER", "dashboard-test")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "dashboard-password")
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE orca_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                received_at REAL NOT NULL
            )
        """)
    app = Flask(__name__)
    app.register_blueprint(dashboard.dashboard_bp)
    return app.test_client()


def test_orca_status_rejects_missing_signature(orca_client):
    response = orca_client.post("/internal/orca/status", data=b'{"tasks":[]}')
    assert response.status_code == 401


def test_orca_status_rejects_invalid_signature(orca_client):
    response = orca_client.post(
        "/internal/orca/status",
        data=b'{"tasks":[]}',
        headers={"X-Orca-Signature": "invalid"},
    )
    assert response.status_code == 401


def test_orca_status_accepts_signed_snapshot_and_dashboard_reads_it(orca_client):
    payload = {
        "tasks": [{"task_id": "task-1", "status": "running"}],
        "dispatches": [{"dispatch_id": "dispatch-1", "status": "ready"}],
        "workers": [{"worker_id": "worker-1", "status": "live"}],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"test-orca-secret", raw, hashlib.sha256).hexdigest()
    posted = orca_client.post(
        "/internal/orca/status",
        data=raw,
        headers={"X-Orca-Signature": signature},
    )
    assert posted.status_code == 200
    read = orca_client.get(
        "/api/dashboard/orca",
        headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"},
    )
    body = read.get_json()
    assert read.status_code == 200
    assert body["tasks"][0]["task_id"] == "task-1"
    assert body["dispatches"][0]["dispatch_id"] == "dispatch-1"
    assert body["workers"][0]["worker_id"] == "worker-1"


def test_orca_status_rejects_oversized_payload(orca_client):
    response = orca_client.post(
        "/internal/orca/status",
        data=b"x" * 65537,
        headers={"X-Orca-Signature": "irrelevant"},
    )
    assert response.status_code == 413


def test_orca_status_rejects_invalid_collection_shape(orca_client):
    raw = json.dumps({"tasks": "not-an-array"}).encode()
    signature = hmac.new(b"test-orca-secret", raw, hashlib.sha256).hexdigest()
    response = orca_client.post(
        "/internal/orca/status",
        data=raw,
        headers={"X-Orca-Signature": signature},
    )
    assert response.status_code == 400
