"""Authenticated queue endpoints for the Mac-local Obsidian bridge.

The endpoints expose only bounded job payloads. They never expose the Obsidian
vault or accept arbitrary filesystem paths.
"""
from __future__ import annotations

import hmac
import os
import re

from flask import Blueprint, current_app, jsonify, request

from core.obsidian_bridge import OBSIDIAN_JOB_TYPE
from obsidian_loop_dispatch import (
    is_repairable_obsidian_incident,
    request_obsidian_incident_repair,
)
from db import (
    cancel_pending_job_by_type,
    claim_pending_job_by_type,
    complete_claimed_job,
    get_job,
    get_job_status_summary,
    has_pending_job_by_type,
)


obsidian_bridge_bp = Blueprint("obsidian_bridge", __name__, url_prefix="/api/obsidian")

_MAX_REPLY_CHARS = 20_000
_MAX_ERROR_CHARS = 2_000
_MAX_JOB_ID = 2**31 - 1
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


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


@obsidian_bridge_bp.route("/pending", methods=["GET"])
def pending():
    """Check for a pending Obsidian job without claiming or mutating it."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        has_pending = has_pending_job_by_type(OBSIDIAN_JOB_TYPE)
    except Exception:
        current_app.logger.exception("OBSIDIAN BRIDGE PENDING ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503

    return jsonify({"ok": True, "pending": has_pending}), 200


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

    stored_result = reply if isinstance(reply, str) and reply.strip() else None
    stored_error = error if isinstance(error, str) and error.strip() else None
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

    diagnostic_category = data.get("diagnostic_category")
    diagnostic_detail = data.get("diagnostic_detail")
    repair_notice = None
    if not success and is_repairable_obsidian_incident(
        diagnostic_category, diagnostic_detail
    ):
        dispatched, dispatch_reason = request_obsidian_incident_repair(
            diagnostic_category, diagnostic_detail, job_id
        )
        if dispatched:
            repair_notice = (
                "自動修復Loopへの起動要求を受け付けました（最大2タスク。"
                "自動マージ・自動デプロイは無効です）。"
                "起動要求の受理は修復完了を意味しません。"
            )
        elif dispatch_reason == "loop_already_running":
            repair_notice = "既存の分散Loopが稼働中のため、新しいLoopは起動していません。"
        elif dispatch_reason == "cooldown_active":
            repair_notice = "連続起動防止の待機時間中のため、新しいLoopは起動していません。"
        elif dispatch_reason in {"github_http_401", "dispatch_http_401"}:
            repair_notice = (
                "GitHub認証エラー（401）。RenderのGITHUB_ACTIONS_DISPATCH_TOKENが"
                "有効か確認してください。トークン値をLINEに送らないでください。"
            )
        elif dispatch_reason in {"github_http_403", "dispatch_http_403"}:
            repair_notice = (
                "GitHub権限エラー（403）。対象リポジトリのActions読み書き権限と"
                "workflow起動権限を確認してください。"
            )
        elif dispatch_reason in {"github_http_404", "dispatch_http_404"}:
            repair_notice = (
                "GitHubのリポジトリまたはworkflowにアクセスできません（404）。"
                "リポジトリ名、workflow名、tokenの対象範囲を確認してください。"
            )
        elif dispatch_reason in {"github_http_429", "dispatch_http_429"}:
            repair_notice = "GitHub APIの利用制限中（429）です。待ってから再確認してください。"
        else:
            # The reason is a fixed internal code or an HTTP status code, never raw user data.
            repair_notice = (
                f"自動修復Loopは起動できませんでした（理由コード: {dispatch_reason}）。"
                "設定とGitHub Actionsの状態確認が必要です。"
            )
        # Never log raw user text, notes, exception messages, or credentials.
        current_app.logger.info(
            "OBSIDIAN AUTOREPAIR category=%s detail=%s job_id=%s dispatched=%s reason=%s",
            diagnostic_category,
            diagnostic_detail,
            job_id,
            dispatched,
            dispatch_reason,
        )

    if isinstance(reply, str) and reply.strip():
        try:
            # LINE credentials stay on the server; the Mac bridge never receives them.
            from app import _line_push

            reply_message = reply.strip()
            if repair_notice:
                reply_message = f"{reply_message}\n\n{repair_notice}"
            _line_push(job["user_id"], reply_message)
        except Exception:
            current_app.logger.exception("OBSIDIAN BRIDGE LINE PUSH ERROR")
            return jsonify(
                {"ok": False, "error": "job completed but LINE notification failed"}
            ), 503

    return jsonify({"ok": True, "status": "completed" if success else "failed"}), 200



def _job_cancel_enabled() -> bool:
    """Cancellation is disabled unless an operator explicitly enables it."""
    return os.environ.get("OBSIDIAN_BRIDGE_ALLOW_JOB_CANCEL", "").strip().lower() == "true"


@obsidian_bridge_bp.route("/jobs/<int:job_id>/status", methods=["GET"])
def job_status(job_id: int):
    """Read-only status for one Obsidian job; never claims or mutates anything."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not 0 < job_id <= _MAX_JOB_ID:
        return jsonify({"ok": False, "error": "job not found"}), 404
    try:
        summary = get_job_status_summary(job_id, OBSIDIAN_JOB_TYPE)
    except Exception:
        current_app.logger.exception("OBSIDIAN BRIDGE STATUS ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if summary is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": summary}), 200


@obsidian_bridge_bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
def job_cancel(job_id: int):
    """Cancel exactly one matching pending job only when the operator feature flag is enabled."""
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not 0 < job_id <= _MAX_JOB_ID:
        return jsonify({"ok": False, "error": "job not found"}), 404
    if not _job_cancel_enabled():
        return jsonify({"ok": False, "error": "job cancellation disabled"}), 403

    data = request.get_json(silent=True)
    expected = data.get("expected_message_sha256") if isinstance(data, dict) else None
    if not isinstance(expected, str) or not _SHA256_HEX_RE.fullmatch(expected):
        return jsonify(
            {"ok": False, "error": "expected_message_sha256 must be 64 lowercase hex characters"}
        ), 400
    try:
        result = cancel_pending_job_by_type(job_id, OBSIDIAN_JOB_TYPE, expected)
    except Exception:
        current_app.logger.exception("OBSIDIAN BRIDGE CANCEL ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503

    outcome = result.get("outcome")
    if outcome == "cancelled":
        current_app.logger.info("OBSIDIAN BRIDGE JOB CANCELLED id=%s", job_id)
        return jsonify({"ok": True, "cancelled": True, "status": "failed"}), 200
    if outcome == "not_found":
        return jsonify({"ok": False, "error": "job not found"}), 404
    if outcome == "message_mismatch":
        return jsonify({"ok": False, "error": "message mismatch"}), 409
    if outcome == "not_pending":
        return jsonify({"ok": False, "error": "job is not pending", "status": result.get("status")}), 409
    return jsonify({"ok": False, "error": "job is not cancellable"}), 409


__all__ = ["obsidian_bridge_bp"]
