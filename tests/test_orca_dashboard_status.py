import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone, timedelta

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
        conn.execute("CREATE TABLE orca_status (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, received_at REAL NOT NULL)")
    app = Flask(__name__)
    app.register_blueprint(dashboard.dashboard_bp)
    return app.test_client()


def post_snapshot(client, payload):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(b"test-orca-secret", raw, hashlib.sha256).hexdigest()
    return client.post("/internal/orca/status", data=raw, headers={"X-Orca-Signature": sig})


def snapshot(**overrides):
    data = {"captured_at": datetime.now(timezone.utc).isoformat(), "run_id": "run-1",
            "source": "orca_collector", "observation_type": "runtime_observation",
            "tasks": [{"id": "t1", "status": "running", "prompt": "PRIVATE"}],
            "dispatches": [{"id": "d1", "status": "ready", "payload": "PRIVATE"}],
            "workers": [{"id": "w1", "status": "live", "argv": ["SECRET"]}],
            "streams": [{"key": "main_star_night", "label": "STAR-NIGHT", "kind": "main",
                         "status": "observed", "task_count": 1, "dispatch_count": 0,
                         "worker_count": 0, "evidence": "matched_runtime_records"},
                        {"key": "side_media_ai", "label": "映像・音楽AI", "kind": "side",
                         "status": "observed", "task_count": 1, "dispatch_count": 0,
                         "worker_count": 0},
                        {"key": "side_core_vocabulary", "label": "英単語コア語彙", "kind": "side",
                         "status": "observed", "task_count": 1, "dispatch_count": 0,
                         "worker_count": 0}]}
    data.update(overrides)
    return data


def test_orca_status_rejects_missing_and_invalid_signatures(orca_client):
    assert orca_client.post("/internal/orca/status", data=b"{}").status_code == 401
    assert orca_client.post("/internal/orca/status", data=b"{}", headers={"X-Orca-Signature": "bad"}).status_code == 401


def test_orca_status_accepts_signed_snapshot_and_redacts_unlisted_fields(orca_client):
    assert post_snapshot(orca_client, snapshot()).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    body = read.get_json()
    assert read.status_code == 200 and body["tasks"][0]["id"] == "t1"
    assert "prompt" not in body["tasks"][0] and "payload" not in body["dispatches"][0]
    assert "argv" not in body["workers"][0]
    assert body["streams"][0]["status"] == "observed"
    assert body["source"] == "orca_collector"
    assert body["observation_type"] == "runtime_observation"
    assert [item["key"] for item in body["streams"]] == ["main_star_night", "side_media_ai", "side_core_vocabulary"]


def test_orca_status_rejects_oversized_and_invalid_collections(orca_client):
    assert orca_client.post("/internal/orca/status", data=b"x" * 65537).status_code == 413
    bad = snapshot(tasks="not-an-array")
    assert post_snapshot(orca_client, bad).status_code == 400


def test_orca_status_rejects_missing_naive_stale_and_future_timestamps(orca_client):
    for value in (None, "2026-01-01T00:00:00", (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),
                  (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()):
        assert post_snapshot(orca_client, snapshot(captured_at=value)).status_code == 400


def test_orca_status_rejects_replayed_or_out_of_order_snapshot(orca_client):
    first = datetime.now(timezone.utc)
    assert post_snapshot(orca_client, snapshot(captured_at=first.isoformat())).status_code == 200
    older = first - timedelta(seconds=1)
    assert post_snapshot(orca_client, snapshot(captured_at=older.isoformat())).status_code == 409


def test_orca_status_reports_stale_based_on_capture_time(orca_client, monkeypatch):
    old = (datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()
    assert post_snapshot(orca_client, snapshot(captured_at=old)).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    assert read.get_json()["status"] == "stale"


def test_dashboard_loop_lists_all_five_development_streams(orca_client):
    response = orca_client.get("/api/dashboard/loop", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    assert response.status_code == 200
    keys = [item["key"] for item in response.get_json()["loop"]["streams"]]
    assert keys == ["main_star_night", "side_task_supply", "side_media_ai", "side_self_improvement", "side_line_full_control", "side_core_vocabulary"]


def test_workflow_self_report_is_not_runtime_observation(orca_client):
    payload = snapshot(source="github_actions", observation_type="workflow_execution")
    assert post_snapshot(orca_client, payload).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    body = read.get_json()
    assert body["source"] == "github_actions"
    assert body["observation_type"] == "workflow_execution"
    assert body["streams"][0]["status"] == "reported"
    assert body["streams"][0]["evidence"] == "workflow_self_report"


def test_legacy_provenance_is_not_promoted_to_observed(orca_client):
    payload = snapshot()
    payload.pop("source")
    payload.pop("observation_type")
    assert post_snapshot(orca_client, payload).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJk"})
    body = read.get_json()
    assert body["source"] == "legacy_unverified"
    assert body["streams"][0]["status"] == "unknown"
