"""Authenticated polling API for the Mac-local OpenClaw worker.

The Mac initiates outbound HTTPS requests; this service never opens a port on the Mac.
"""
from __future__ import annotations

import hmac
import os

from flask import Blueprint, current_app, jsonify, request

from core.openclaw_bridge import OPENCLAW_JOB_TYPE
from db import claim_pending_job_by_type, complete_claimed_job, get_job

openclaw_bridge_bp = Blueprint("openclaw_bridge", __name__, url_prefix="/api/openclaw")
_MAX_REPLY_CHARS = 12000
_MAX_ERROR_CHARS = 1000


def _authorized() -> bool:
    expected = os.environ.get("OPENCLAW_BRIDGE_KEY", "")
    provided = request.headers.get("X-OpenClaw-Bridge-Key", "")
    return bool(expected and provided and hmac.compare_digest(expected, provided))


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
    try:
        updated = complete_claimed_job(job_id, token, success=success, result=stored,
                                       last_error=(error[:_MAX_ERROR_CHARS] if error else None))
    except Exception:
        current_app.logger.exception("OPENCLAW BRIDGE COMPLETE ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if not updated:
        return jsonify({"ok": False, "error": "claim mismatch"}), 409
    if stored:
        try:
            # Import lazily to avoid the app/routes import cycle at startup.
            from app import _line_push
            _line_push(job["user_id"], stored)
        except Exception:
            current_app.logger.exception("OPENCLAW BRIDGE LINE PUSH ERROR")
            return jsonify({"ok": True, "status": "completed", "push_warning": True}), 200
    return jsonify({"ok": True, "status": "completed" if success else "failed"}), 200
