"""Authenticated polling API for the Mac-local OpenClaw worker.

The Mac initiates outbound HTTPS requests; this service never opens a port on the Mac.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from core.openclaw_bridge import OPENCLAW_JOB_TYPE
from db import DB, claim_pending_job_by_type, complete_claimed_job, get_job

openclaw_bridge_bp = Blueprint("openclaw_bridge", __name__, url_prefix="/api/openclaw")
_MAX_REPLY_CHARS = 12000
_MAX_ERROR_CHARS = 1000


def _key_fingerprint(value: str) -> str:
    """Return a short diagnostic fingerprint without exposing the credential."""
    if not value:
        return "absent"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _authorized() -> bool:
    expected = os.environ.get("OPENCLAW_BRIDGE_KEY", "")
    provided = request.headers.get("X-OpenClaw-Bridge-Key", "")
    # Enforce the same minimum strength on the API as on the enqueue path.
    expected_length_ok = len(expected) >= 24
    matched = bool(
        expected_length_ok
        and provided
        and hmac.compare_digest(expected, provided)
    )
    if not matched:
        # Never log either secret value; lengths and presence are sufficient to
        # distinguish a missing header from a mismatched credential.
        current_app.logger.warning(
            "OPENCLAW BRIDGE AUTH REJECTED expected_present=%s "
            "expected_length_ok=%s header_present=%s header_length=%d "
            "expected_fp=%s provided_fp=%s matched=%s",
            bool(expected),
            expected_length_ok,
            bool(provided),
            len(provided),
            _key_fingerprint(expected),
            _key_fingerprint(provided),
            matched,
        )
    return matched


def _read_queue_summary() -> dict[str, int]:
    """Read aggregate OpenClaw queue counts using a SQLite-enforced read-only connection."""
    uri = Path(DB).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*)
            FROM jobs
            WHERE job_type=?
            GROUP BY status
            """,
            (OPENCLAW_JOB_TYPE,),
        ).fetchall()
    summary = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for status, count in rows:
        if status in summary:
            summary[status] = int(count)
    return summary


@openclaw_bridge_bp.route("/status", methods=["GET"])
def status():
    """Authenticate and inspect queue counts without claiming or changing jobs."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        queue = _read_queue_summary()
    except Exception:
        current_app.logger.exception("OPENCLAW BRIDGE STATUS ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    return jsonify({"ok": True, "queue": queue}), 200


@openclaw_bridge_bp.route("/claim", methods=["POST"])
def claim():
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        job = claim_pending_job_by_type(OPENCLAW_JOB_TYPE)
    except Exception:
        current_app.logger.exception("OPENCLAW BRIDGE CLAIM ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if job is None:
        return jsonify({"ok": True, "job": None}), 200
    return jsonify({"ok": True, "job": {
        "id": job["id"], "user_id": job["user_id"],
        "message": job["message"], "claim_token": job["claim_token"],
    }}), 200


@openclaw_bridge_bp.route("/complete", methods=["POST"])
def complete():
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400
    job_id, token, success = data.get("job_id"), data.get("claim_token"), data.get("success")
    reply, error = data.get("reply"), data.get("error")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        return jsonify({"ok": False, "error": "job_id is required"}), 400
    if not isinstance(token, str) or not token.strip():
        return jsonify({"ok": False, "error": "claim_token is required"}), 400
    if not isinstance(success, bool):
        return jsonify({"ok": False, "error": "success must be boolean"}), 400
    if reply is not None and (not isinstance(reply, str) or len(reply) > _MAX_REPLY_CHARS):
        return jsonify({"ok": False, "error": "reply exceeds 12000 characters"}), 400
    if error is not None and (not isinstance(error, str) or len(error) > _MAX_ERROR_CHARS):
        return jsonify({"ok": False, "error": "error exceeds 1000 characters"}), 400
    job = get_job(job_id)
    if job is None or job.get("job_type") != OPENCLAW_JOB_TYPE:
        return jsonify({"ok": False, "error": "job not found"}), 404
    if job.get("status") != "running" or job.get("claim_token") != token:
        return jsonify({"ok": False, "error": "claim mismatch"}), 409
    stored = reply.strip() if isinstance(reply, str) and reply.strip() else None
    # Always notify the LINE user when the worker reports a failure; do not expose
    # raw local errors or stderr through the chat channel.
    notification = stored if stored else (None if success else
        "OpenClawの処理に失敗しました。時間をおいて再試行してください。")
    try:
        updated = complete_claimed_job(job_id, token, success=success, result=stored,
                                       last_error=(error[:_MAX_ERROR_CHARS] if error else None))
    except Exception:
        current_app.logger.exception("OPENCLAW BRIDGE COMPLETE ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if not updated:
        return jsonify({"ok": False, "error": "claim mismatch"}), 409
    if notification:
        try:
            # Import lazily to avoid the app/routes import cycle at startup.
            from app import _line_push
            _line_push(job["user_id"], notification)
        except Exception:
            current_app.logger.exception("OPENCLAW BRIDGE LINE PUSH ERROR")
            return jsonify({"ok": True, "status": "completed" if success else "failed", "push_warning": True}), 200
    return jsonify({"ok": True, "status": "completed" if success else "failed"}), 200
