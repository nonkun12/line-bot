import hashlib
import hmac
import json
import sqlite3
from pathlib import Path
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
    task = {
        "task_id": "task-rea", "status": "BLOCKED",
        "rea_artifact_status": "HOLD", "rea_artifact_reason_code": "risk_unknown",
        "rea_artifact_evidence_sha256": "d" * 64,
        "rea_artifact_execution_authorized": False, "rea_artifact_patch_authorized": False,
        "rea_artifact_hold_clear_authorized": False, "rea_artifact_merge_deploy_authorized": False,
        "raw_diff": "must not leak",
    }
    assert post_snapshot(orca_client, snapshot(tasks=[task])).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    body = read.get_json()
    assert read.status_code == 200 and body["tasks"][0]["rea_artifact_status"] == "HOLD"
    assert body["tasks"][0]["rea_artifact_reason_code"] == "risk_unknown"
    assert body["tasks"][0]["rea_artifact_evidence_sha256"] == "d" * 64
    assert body["tasks"][0]["rea_artifact_execution_authorized"] is False
    assert "raw_diff" not in body["tasks"][0]
    assert "payload" not in body["dispatches"][0]
    assert "argv" not in body["workers"][0]
    assert body["streams"][0]["status"] == "observed"
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


def test_orca_dashboard_exposes_sanitized_rsi_review_summary(orca_client):
    review = {
        "phase": "RSI_REVIEW", "status": "PASS", "reason_code": "rea_review_pass_proposal_only",
        "next_action": "REQUEST_HUMAN_REVIEW", "repository": "nonkun12/line-bot", "head_sha": "a" * 40,
        "review_count": 1, "review_evidence_event_ids": ["orchestra-rea:event-1"],
        "allow_continue": False, "proposal_only": True, "execution_authorized": False,
        "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False,
        "scheduler_started": False, "model_activated": False, "raw_feedback": "must not leak",
    }
    assert post_snapshot(orca_client, snapshot(rsi_review=review)).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    body = read.get_json()
    assert body["rsi_review"]["status"] == "PASS"
    assert body["rsi_review"]["allow_continue"] is False
    assert "raw_feedback" not in body["rsi_review"]


def test_orca_dashboard_exposes_sha_bound_rea_handoff(orca_client):
    review = {
        "phase": "REA_VERIFICATION_HANDOFF", "status": "HOLD", "gate": "HOLD",
        "reason_code": "risk_unknown_no_promotion", "next_action": "REQUEST_HUMAN_REVIEW",
        "repository": "nonkun12/line-bot", "head_sha": "a" * 40, "review_count": 1,
        "review_evidence_event_ids": ["orchestra-rea:source-run-123", "orchestra-rea:verification-run-456"],
        "source_run_id": 123, "verification_run_id": 456,
        "candidate_evidence_sha256": "b" * 64, "receipt_sha256": "c" * 64,
        "allow_continue": False, "proposal_only": True, "execution_authorized": False,
        "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False,
        "scheduler_started": False, "model_activated": False,
    }
    assert post_snapshot(orca_client, snapshot(rsi_review=review)).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJk"})
    body = read.get_json()["rsi_review"]
    assert body["gate"] == "HOLD" and body["head_sha"] == "a" * 40
    assert body["source_run_id"] == 123 and body["verification_run_id"] == 456
    assert body["candidate_evidence_sha256"] == "b" * 64
    assert body["receipt_sha256"] == "c" * 64
    assert body["execution_authorized"] is False


def test_orca_dashboard_rejects_rsi_review_authority_escalation(orca_client):
    review = {"status": "PASS", "review_count": 0, "review_evidence_event_ids": [],
        "proposal_only": True, "allow_continue": True, "execution_authorized": False,
        "patch_authorized": False, "hold_clear_authorized": False, "merge_deploy_authorized": False,
        "scheduler_started": False, "model_activated": False}
    assert post_snapshot(orca_client, snapshot(rsi_review=review)).status_code == 400

def test_orca_dashboard_rejects_rea_artifact_authority_escalation(orca_client):
    task = {
        "task_id": "task-rea", "rea_artifact_status": "PASS",
        "rea_artifact_evidence_sha256": "e" * 64,
        "rea_artifact_execution_authorized": True,
        "rea_artifact_patch_authorized": False,
        "rea_artifact_hold_clear_authorized": False,
        "rea_artifact_merge_deploy_authorized": False,
    }
    assert post_snapshot(orca_client, snapshot(tasks=[task])).status_code == 400


def test_orca_dashboard_exposes_distinct_work_finder_lifecycle_counts(orca_client):
    work_finder = {
        "cycle_status": "WORK_FOUND", "next_action": "human_review_candidates",
        "execution_eligibility_status": "not_proven",
        "candidate_policy": "review_only_no_execution_approval",
        "safety": {"read_only": True, "execution_approval_granted": False},
        "discovered_candidate_count": 4, "review_pending_count": 4,
        "completed_task_count": 8, "catalog_task_count": 50,
        "runtime_queue_task_count": 0, "held_task_count": 6,
        "resume_review_required_count": 2, "scanned_target_pairs": 10,
        "candidate_preview": [{"id": "review-coverage-gap-a1b2", "target_test": "tests/test_x.py", "source_function": "do_work", "evidence": "core/x.py:12", "status": "REVIEW_REQUIRED"}],
    }
    assert post_snapshot(orca_client, snapshot(work_finder=work_finder)).status_code == 200
    read = orca_client.get("/api/dashboard/orca", headers={"Authorization": "Basic ZGFzaGJvYXJkLXRlc3Q6ZGFzaGJvYXJkLXBhc3N3b3Jk"})
    body = read.get_json()["work_finder"]
    assert body["discovered_candidate_count"] == 4
    assert body["review_pending_count"] == 4
    assert body["completed_task_count"] == 8
    assert body["candidate_preview"][0]["source_function"] == "do_work"
    assert "execution_eligible_count" not in body
    assert body["execution_eligibility_status"] == "not_proven"


def test_orca_dashboard_rejects_work_finder_authority_escalation(orca_client):
    unsafe = {
        "cycle_status": "WORK_FOUND", "next_action": "human_review_candidates",
        "execution_eligibility_status": "verified",
        "candidate_policy": "review_only_no_execution_approval",
        "safety": {"read_only": True, "execution_approval_granted": True},
        "discovered_candidate_count": 1, "review_pending_count": 1,
        "completed_task_count": 0,
    }
    assert post_snapshot(orca_client, snapshot(work_finder=unsafe)).status_code == 400


def test_orca_dashboard_declares_candidate_preview_before_work_finder_card():
    source = (Path(__file__).resolve().parents[1] / "static/js/dashboard.js").read_text(encoding="utf-8")
    preview_declaration = source.index("const candidatePreview=")
    card_declaration = source.index("const workFinderCard=wf")
    assert preview_declaration < card_declaration
