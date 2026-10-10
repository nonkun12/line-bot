"""Regression tests for Obsidian job status and cancellation endpoints."""
import hashlib
import json
import logging
import os
import sqlite3
import stat
from contextlib import closing

import pytest
from flask import Flask

import db
import routes.obsidian_bridge as bridge
from routes.obsidian_bridge import obsidian_bridge_bp

KEY = "bridge-key-SECRET-VALUE"
HEADERS = {"X-Obsidian-Bridge-Key": KEY}
TEST_MESSAGE = "Obsidianに保存 test/secret-note.md: SECRET-BODY-123"
OTHER_MESSAGE = "Obsidianに保存 other/real-note.md: REAL-USER-DATA"


def sha(message):
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def make_app():
    app = Flask(__name__)
    app.register_blueprint(obsidian_bridge_bp)
    return app


@pytest.fixture(autouse=True)
def _ready(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", KEY)
    monkeypatch.setenv("OBSIDIAN_BRIDGE_ALLOW_JOB_CANCEL", "true")
    db.init_db()


def new_job(message=TEST_MESSAGE, job_type="obsidian", user_id="U-secret-user"):
    return db.create_job(user_id, message, job_type=job_type, source="line", max_retries=3)


def snapshot(job_id):
    with closing(sqlite3.connect(db.DB)) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        checkpoints = conn.execute(
            "SELECT COUNT(*) FROM job_checkpoints WHERE job_id=?", (job_id,)
        ).fetchone()[0]
    return row, checkpoints


def all_rows():
    with closing(sqlite3.connect(db.DB)) as conn:
        return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


def test_status_summary_hides_body_user_result_and_token():
    job_id = new_job()
    claimed = db.claim_pending_job_by_type("obsidian")
    summary = db.get_job_status_summary(job_id, "obsidian")
    assert summary["status"] == "running"
    assert summary["has_claim"] is True
    assert summary["message_sha256"] == sha(TEST_MESSAGE)
    assert summary["message_chars"] == len(TEST_MESSAGE)
    assert set(summary) == {
        "id", "job_type", "status", "retry_count", "max_retries",
        "message_sha256", "message_chars", "has_claim", "has_error",
        "created_at", "updated_at",
    }
    dumped = json.dumps(summary, ensure_ascii=False)
    assert "SECRET-BODY-123" not in dumped
    assert "U-secret-user" not in dumped
    assert claimed["claim_token"] not in dumped


def test_status_summary_only_for_matching_type_and_valid_id():
    ai_job = new_job(job_type="ai_task")
    assert db.get_job_status_summary(ai_job, "obsidian") is None
    for bad in (0, -1, 2**31, 2**70, True, "1", None):
        assert db.get_job_status_summary(bad, "obsidian") is None
    assert db.get_job_status_summary(999, "obsidian") is None


def test_status_summary_is_read_only_and_never_claims():
    job_id = new_job()
    before = all_rows()
    db.get_job_status_summary(job_id, "obsidian")
    assert all_rows() == before
    assert db.has_pending_job_by_type("obsidian") is True
    with closing(db._readonly_conn()) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE jobs SET status='failed'")


def test_cancel_changes_only_the_target_and_records_previous_state():
    target = new_job()
    other = new_job(OTHER_MESSAGE)
    other_before = snapshot(other)
    result = db.cancel_pending_job_by_type(target, "obsidian", sha(TEST_MESSAGE))
    assert result == {"outcome": "cancelled", "status": "failed"}
    row = db.get_job(target)
    assert row["status"] == "failed"
    assert row["last_error"] == "cancelled by operator"
    assert row["claim_token"] is None
    assert row["message"] == TEST_MESSAGE
    assert snapshot(other) == other_before
    checkpoint = db.get_latest_checkpoint(target)
    assert checkpoint["step_name"] == "operator_cancel"
    previous = json.loads(checkpoint["output_snapshot"])
    assert previous["previous_status"] == "pending"
    assert previous["message_sha256"] == sha(TEST_MESSAGE)
    assert "SECRET-BODY-123" not in checkpoint["output_snapshot"]


def test_cancel_changes_only_target_when_messages_are_identical():
    first = new_job()
    second = new_job()
    db.cancel_pending_job_by_type(first, "obsidian", sha(TEST_MESSAGE))
    assert db.get_job(first)["status"] == "failed"
    assert db.get_job(second)["status"] == "pending"


def test_cancelled_job_is_never_claimed_and_other_jobs_still_work():
    target = new_job()
    other = new_job(OTHER_MESSAGE)
    db.cancel_pending_job_by_type(target, "obsidian", sha(TEST_MESSAGE))
    claimed = db.claim_pending_job_by_type("obsidian")
    assert claimed["id"] == other
    assert db.claim_pending_job_by_type("obsidian") is None
    db.complete_claimed_job(other, claimed["claim_token"], success=True, result="ok")
    assert db.has_pending_job_by_type("obsidian") is False
    assert db.get_job(target)["status"] == "failed"


def _make_running(message=TEST_MESSAGE):
    job_id = new_job(message)
    claimed = db.claim_pending_job_by_type("obsidian")
    assert claimed is not None and claimed["id"] == job_id
    return job_id


def _make_completed():
    job_id = _make_running()
    token = db.get_job(job_id)["claim_token"]
    assert db.complete_claimed_job(job_id, token, success=True, result="saved")
    return job_id


def _make_failed():
    job_id = _make_running()
    token = db.get_job(job_id)["claim_token"]
    assert db.complete_claimed_job(job_id, token, success=False, last_error="boom")
    return job_id


def _make_pending_with_token():
    job_id = new_job()
    with closing(sqlite3.connect(db.DB)) as conn:
        with conn:
            conn.execute("UPDATE jobs SET claim_token='held' WHERE id=?", (job_id,))
    return job_id


@pytest.mark.parametrize(
    "setup, expected_outcome, expected_status",
    [
        (_make_running, "not_pending", "running"),
        (_make_completed, "not_pending", "completed"),
        (_make_failed, "not_pending", "failed"),
        (_make_pending_with_token, "not_cancellable", "pending"),
    ],
)
def test_cancel_refuses_non_pending_states_without_change(setup, expected_outcome, expected_status):
    job_id = setup()
    before = snapshot(job_id)
    result = db.cancel_pending_job_by_type(job_id, "obsidian", sha(TEST_MESSAGE))
    assert result == {"outcome": expected_outcome, "status": expected_status}
    assert snapshot(job_id) == before


def test_cancel_refuses_message_mismatch_wrong_type_and_missing_job():
    target = new_job()
    before = snapshot(target)
    assert db.cancel_pending_job_by_type(target, "obsidian", sha("different"))["outcome"] == "message_mismatch"
    assert snapshot(target) == before
    ai_job = new_job(job_type="ai_task")
    ai_before = snapshot(ai_job)
    assert db.cancel_pending_job_by_type(ai_job, "obsidian", sha(TEST_MESSAGE))["outcome"] == "not_found"
    assert snapshot(ai_job) == ai_before
    assert db.cancel_pending_job_by_type(4242, "obsidian", sha(TEST_MESSAGE))["outcome"] == "not_found"


def test_second_cancel_is_a_noop():
    job_id = new_job()
    assert db.cancel_pending_job_by_type(job_id, "obsidian", sha(TEST_MESSAGE))["outcome"] == "cancelled"
    after_first = snapshot(job_id)
    assert db.cancel_pending_job_by_type(job_id, "obsidian", sha(TEST_MESSAGE)) == {
        "outcome": "not_pending", "status": "failed"
    }
    assert snapshot(job_id) == after_first


@pytest.mark.parametrize(
    "job_id, digest",
    [
        (1, "ABC" * 22), (1, sha(TEST_MESSAGE).upper()), (1, sha(TEST_MESSAGE)[:63]),
        (0, sha(TEST_MESSAGE)), (-5, sha(TEST_MESSAGE)), (True, sha(TEST_MESSAGE)),
        (2**40, sha(TEST_MESSAGE)),
    ],
)
def test_cancel_rejects_invalid_arguments_without_change(job_id, digest):
    new_job()
    before = all_rows()
    with pytest.raises(ValueError):
        db.cancel_pending_job_by_type(job_id, "obsidian", digest)
    assert all_rows() == before


def test_cancel_is_atomic_when_audit_record_cannot_be_written():
    job_id = new_job()
    with closing(sqlite3.connect(db.DB)) as conn:
        with conn:
            conn.execute("DROP TABLE job_checkpoints")
    before = all_rows()
    with pytest.raises(sqlite3.OperationalError):
        db.cancel_pending_job_by_type(job_id, "obsidian", sha(TEST_MESSAGE))
    assert all_rows() == before
    assert db.get_job(job_id)["status"] == "pending"


def test_backup_database_creates_private_consistent_copy_and_refuses_overwrite(tmp_path):
    job_id = new_job()
    before = all_rows()
    destination = tmp_path / "chat.db.bak"
    path = db.backup_database(destination)
    assert path == str(destination.resolve())
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with closing(sqlite3.connect(destination)) as conn:
        copied = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    assert copied == before
    assert all_rows() == before
    assert db.get_job(job_id)["status"] == "pending"
    with pytest.raises(FileExistsError):
        db.backup_database(destination)
    with pytest.raises(FileNotFoundError):
        db.backup_database(tmp_path / "missing-dir" / "x.db")


ROUTES = [
    ("get", "/api/obsidian/pending", None),
    ("post", "/api/obsidian/claim", {}),
    ("post", "/api/obsidian/complete", {}),
    ("get", "/api/obsidian/jobs/1/status", None),
    ("post", "/api/obsidian/jobs/1/cancel", {"expected_message_sha256": "0" * 64}),
]


def call(method, path, body=None, headers=None):
    client = make_app().test_client()
    kwargs = {"headers": headers or {}}
    if method == "post":
        kwargs["json"] = body if body is not None else {}
    return getattr(client, method)(path, **kwargs)


@pytest.mark.parametrize("method, path, body", ROUTES)
@pytest.mark.parametrize("headers", [{}, {"X-Obsidian-Bridge-Key": "wrong"}, {"X-Obsidian-Bridge-Key": ""}])
def test_every_endpoint_rejects_missing_or_wrong_key_before_database_touch(
    monkeypatch, method, path, body, headers
):
    def boom(*args, **kwargs):
        raise AssertionError("database must not be touched without a valid key")
    for name in (
        "has_pending_job_by_type", "claim_pending_job_by_type", "get_job",
        "complete_claimed_job", "get_job_status_summary", "cancel_pending_job_by_type",
    ):
        monkeypatch.setattr(bridge, name, boom)
    response = call(method, path, body, headers)
    assert response.status_code == 401
    assert response.get_json() == {"ok": False, "error": "unauthorized"}


def test_cancel_route_is_disabled_unless_explicitly_enabled(monkeypatch):
    job_id = new_job()
    before = all_rows()
    monkeypatch.setenv("OBSIDIAN_BRIDGE_ALLOW_JOB_CANCEL", "false")
    response = call("post", f"/api/obsidian/jobs/{job_id}/cancel",
                    {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS)
    assert response.status_code == 403
    assert all_rows() == before


def test_endpoints_reject_when_server_has_no_bridge_key(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_BRIDGE_KEY", raising=False)
    assert call("get", "/api/obsidian/jobs/1/status", headers=HEADERS).status_code == 401
    assert call("post", "/api/obsidian/jobs/1/cancel",
                {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS).status_code == 401


@pytest.mark.parametrize("path", [
    "/api/obsidian/jobs/abc/status", "/api/obsidian/jobs/-1/status",
    "/api/obsidian/jobs/1.5/status", "/api/obsidian/jobs/0/status",
    "/api/obsidian/jobs/99999999999999999999/status",
    "/api/obsidian/jobs/1%2F..%2Fclaim/status",
])
def test_status_rejects_bad_ids_and_path_tricks(monkeypatch, path):
    new_job()
    before = all_rows()
    monkeypatch.setattr(bridge, "claim_pending_job_by_type",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("claim must not run")))
    response = call("get", path, headers=HEADERS)
    assert response.status_code == 404
    assert all_rows() == before


@pytest.mark.parametrize("path", [
    "/api/obsidian/jobs/abc/cancel", "/api/obsidian/jobs/-1/cancel",
    "/api/obsidian/jobs/0/cancel", "/api/obsidian/jobs/99999999999999999999/cancel",
    "/api/obsidian/jobs/1/../claim",
])
def test_cancel_rejects_bad_ids_and_path_tricks(monkeypatch, path):
    new_job()
    before = all_rows()
    monkeypatch.setattr(bridge, "claim_pending_job_by_type",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("claim must not run")))
    response = call("post", path, {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS)
    assert response.status_code != 200
    assert all_rows() == before


def test_status_route_returns_summary_without_secrets():
    job_id = new_job()
    response = call("get", f"/api/obsidian/jobs/{job_id}/status", headers=HEADERS)
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["job"]["status"] == "pending"
    assert body["job"]["message_sha256"] == sha(TEST_MESSAGE)
    raw = response.get_data(as_text=True)
    for secret in ("SECRET-BODY-123", "U-secret-user", KEY, "claim_token"):
        assert secret not in raw
    assert db.get_job(job_id)["status"] == "pending"


def test_status_route_404_for_missing_or_non_obsidian_job():
    ai_job = new_job(job_type="ai_task")
    assert call("get", "/api/obsidian/jobs/999/status", headers=HEADERS).status_code == 404
    assert call("get", f"/api/obsidian/jobs/{ai_job}/status", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("body", [
    None, {}, {"expected_message_sha256": ""}, {"expected_message_sha256": sha(TEST_MESSAGE).upper()},
    {"expected_message_sha256": sha(TEST_MESSAGE)[:10]}, {"expected_message_sha256": 123},
    {"message": TEST_MESSAGE},
])
def test_cancel_route_requires_hash_without_changes(body):
    job_id = new_job()
    before = all_rows()
    response = call("post", f"/api/obsidian/jobs/{job_id}/cancel", body, HEADERS)
    assert response.status_code == 400
    assert all_rows() == before


def test_cancel_route_rejects_non_object_json():
    job_id = new_job()
    before = all_rows()
    response = make_app().test_client().post(
        f"/api/obsidian/jobs/{job_id}/cancel", json=["x"], headers=HEADERS
    )
    assert response.status_code == 400
    assert all_rows() == before


def test_cancel_route_happy_path_leaks_nothing_in_response_or_logs(caplog, capsys):
    target = new_job()
    other = new_job(OTHER_MESSAGE)
    other_before = snapshot(other)
    with caplog.at_level(logging.DEBUG):
        response = call(
            "post", f"/api/obsidian/jobs/{target}/cancel",
            {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS,
        )
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "cancelled": True, "status": "failed"}
    assert db.get_job(target)["status"] == "failed"
    assert snapshot(other) == other_before
    output = capsys.readouterr()
    haystack = "\n".join([response.get_data(as_text=True), caplog.text, output.out, output.err])
    for secret in ("SECRET-BODY-123", "REAL-USER-DATA", "U-secret-user", KEY, "http"):
        assert secret not in haystack


def test_cancel_route_conflicts_leave_database_untouched():
    running = _make_running(OTHER_MESSAGE)
    running_before = snapshot(running)
    pending = new_job()
    wrong_hash = call(
        "post", f"/api/obsidian/jobs/{pending}/cancel",
        {"expected_message_sha256": sha("other text")}, HEADERS,
    )
    assert wrong_hash.status_code == 409
    assert wrong_hash.get_json() == {"ok": False, "error": "message mismatch"}
    assert db.get_job(pending)["status"] == "pending"
    response = call(
        "post", f"/api/obsidian/jobs/{running}/cancel",
        {"expected_message_sha256": sha(OTHER_MESSAGE)}, HEADERS,
    )
    assert response.status_code == 409
    assert response.get_json() == {
        "ok": False, "error": "job is not pending", "status": "running"
    }
    assert snapshot(running) == running_before
    missing = call(
        "post", "/api/obsidian/jobs/999/cancel",
        {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS,
    )
    assert missing.status_code == 404


def test_cancel_route_hides_internal_errors(monkeypatch):
    job_id = new_job()
    def explode(*args, **kwargs):
        raise RuntimeError("INTERNAL-DETAIL-SECRET")
    monkeypatch.setattr(bridge, "cancel_pending_job_by_type", explode)
    response = call(
        "post", f"/api/obsidian/jobs/{job_id}/cancel",
        {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS,
    )
    assert response.status_code == 503
    assert response.get_json() == {"ok": False, "error": "bridge unavailable"}
    assert "INTERNAL-DETAIL-SECRET" not in response.get_data(as_text=True)


def test_claim_route_behaviour_skips_cancelled_job():
    target = new_job()
    other = new_job(OTHER_MESSAGE)
    call("get", f"/api/obsidian/jobs/{target}/status", headers=HEADERS)
    call("get", "/api/obsidian/pending", headers=HEADERS)
    call("post", f"/api/obsidian/jobs/{target}/cancel",
         {"expected_message_sha256": sha(TEST_MESSAGE)}, HEADERS)
    claim = call("post", "/api/obsidian/claim", {}, HEADERS)
    assert claim.status_code == 200
    job = claim.get_json()["job"]
    assert job["id"] == other and job["message"] == OTHER_MESSAGE
    assert isinstance(job["claim_token"], str) and len(job["claim_token"]) >= 20
    complete = call(
        "post", "/api/obsidian/complete",
        {"job_id": other, "claim_token": job["claim_token"], "success": True}, HEADERS,
    )
    assert complete.status_code == 200
    assert complete.get_json() == {"ok": True, "status": "completed"}
    assert call("get", "/api/obsidian/pending", headers=HEADERS).get_json() == {
        "ok": True, "pending": False
    }
    assert call("post", "/api/obsidian/claim", {}, HEADERS).get_json() == {"ok": True, "job": None}
