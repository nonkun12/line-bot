"""Authenticated queue endpoints for the Mac-local Obsidian bridge.

The endpoints expose only bounded job payloads. They never expose the Obsidian
vault or accept arbitrary filesystem paths.
"""
from __future__ import annotations

import hmac
import os

from flask import Blueprint, current_app, jsonify, request

from core.obsidian_bridge import OBSIDIAN_JOB_TYPE
from db import claim_pending_job_by_type, complete_claimed_job, get_job


obsidian_bridge_bp = Blueprint("obsidian_bridge", __name__, url_prefix="/api/obsidian")

_MAX_REPLY_CHARS = 20_000
_MAX_ERROR_CHARS = 2_000


def _authorized() -> bool:
    expected = os.environ.get("OBSIDIAN_BRIDGE_KEY", "")
    provided = request.headers.get("X-Obsidian-Bridge-Key", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(str(provided), str(expected))


@obsidian_bridge_bp.route("/claim", methods=["POST"])
def claim():
    """Claim one pending Obsidian job for a local bridge process."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        job = claim_pending_job_by_type(OBSIDIAN_JOB_TYPE)
    except Exception:
        current_app.logger.exception("OBSIDIAN BRIDGE CLAIM ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503

    if job is None:
        return jsonify({"ok": True, "job": None}), 200

    return jsonify(
        {
            "ok": True,
            "job": {
                "id": job["id"],
                "user_id": job["user_id"],
                "message": job["message"],
                "claim_token": job["claim_token"],
            },
        }
    ), 200


@obsidian_bridge_bp.route("/complete", methods=["POST"])
def complete():
    """Complete exactly the job previously claimed by this bridge."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    claim_token = data.get("claim_token")
    success = data.get("success")
    reply = data.get("reply")
    error = data.get("error")

    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        return jsonify({"ok": False, "error": "job_id is required"}), 400
    if not isinstance(claim_token, str) or not claim_token.strip():
        return jsonify({"ok": False, "error": "claim_token is required"}), 400
    if not isinstance(success, bool):
        return jsonify({"ok": False, "error": "success must be boolean"}), 400
    if reply is not None and (
        not isinstance(reply, str) or len(reply) > _MAX_REPLY_CHARS
    ):
        return jsonify({"ok": False, "error": "reply exceeds 20000 characters"}), 400
    if error is not None and (
        not isinstance(error, str) or len(error) > _MAX_ERROR_CHARS
    ):
        return jsonify({"ok": False, "error": "error exceeds 2000 characters"}), 400

    job = get_job(job_id)
    if job is None or job["job_type"] != OBSIDIAN_JOB_TYPE:
        return jsonify({"ok": False, "error": "job not found"}), 404
    if job["status"] != "running":
        return jsonify({"ok": False, "error": "job is not claimable"}), 409

    stored_result = reply if success else None
    stored_error = error if not success else None
    try:
        updated = complete_claimed_job(
            job_id,
            claim_token,
            success=success,
            result=stored_result,
            last_error=stored_error,
        )
    except Exception:
        current_app.logger.exception("OBSIDIAN BRIDGE COMPLETE ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503

    if not updated:
        return jsonify({"ok": False, "error": "claim token rejected"}), 409

    if success and isinstance(reply, str) and reply.strip():
        try:
            # LINE credentials stay on the server; the Mac bridge never receives them.
            from app import _line_push

            _line_push(job["user_id"], reply.strip())
        except Exception:
            current_app.logger.exception("OBSIDIAN BRIDGE LINE PUSH ERROR")
            return jsonify(
                {"ok": False, "error": "job completed but LINE notification failed"}
            ), 503

    return jsonify({"ok": True, "status": "completed" if success else "failed"}), 200


__all__ = ["obsidian_bridge_bp"]
