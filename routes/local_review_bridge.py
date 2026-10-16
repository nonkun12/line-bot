"""Isolated authenticated endpoints for Mac-local code-review jobs.

This bridge never handles Obsidian jobs and never edits, merges, or deploys code.
The Mac worker must independently verify the repository checkout and both SHAs.
"""
from __future__ import annotations

import hmac
import json
import os
import re

from flask import Blueprint, current_app, jsonify, request

from core.local_review_jobs import REVIEW_JOB_TYPE, build_review_payload
from db import (
    claim_pending_job_by_type,
    complete_claimed_job,
    get_job,
    get_job_status_summary,
    has_pending_job_by_type,
)

local_review_bridge_bp = Blueprint(
    "local_review_bridge", __name__, url_prefix="/api/local-review"
)

_MAX_JOB_ID = 2**31 - 1
_MAX_SUMMARY_CHARS = 4_000
_MAX_FINDINGS = 100
_MAX_FIELD_CHARS = 4_000
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def _authorized() -> bool:
    expected = os.environ.get("LOCAL_REVIEW_BRIDGE_KEY", "")
    provided = request.headers.get("X-Local-Review-Bridge-Key", "")
    return bool(expected and provided and hmac.compare_digest(expected, provided))


def _job_id_valid(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= _MAX_JOB_ID


def _valid_payload(raw: str):
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != 1 or payload.get("kind") != REVIEW_JOB_TYPE:
            return None
        # Reuse the central allowlist/SHA validator, then compare normalized JSON fields.
        canonical = json.loads(
            build_review_payload(
                payload.get("repository"), payload.get("base_sha"), payload.get("head_sha")
            )
        )
        if canonical != payload:
            return None
        return canonical
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _valid_findings(findings) -> bool:
    if not isinstance(findings, list) or len(findings) > _MAX_FINDINGS:
        return False
    for finding in findings:
        if not isinstance(finding, dict):
            return False
        if finding.get("severity") not in _SEVERITIES:
            return False
        for field in ("file", "issue", "evidence", "recommendation"):
            value = finding.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > _MAX_FIELD_CHARS:
                return False
    return True


@local_review_bridge_bp.route("/pending", methods=["GET"])
def pending():
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        value = has_pending_job_by_type(REVIEW_JOB_TYPE)
    except Exception:
        current_app.logger.exception("LOCAL REVIEW PENDING ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    return jsonify({"ok": True, "pending": value}), 200


@local_review_bridge_bp.route("/claim", methods=["POST"])
def claim():
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        job = claim_pending_job_by_type(REVIEW_JOB_TYPE, stale_after_seconds=900)
    except Exception:
        current_app.logger.exception("LOCAL REVIEW CLAIM ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if job is None:
        return jsonify({"ok": True, "job": None}), 200

    payload = _valid_payload(job.get("message", ""))
    if payload is None:
        # Do not expose the malformed payload. Fail this exact claimed job closed.
        try:
            complete_claimed_job(
                job["id"], job["claim_token"], success=False,
                result=None, last_error="invalid local review payload",
            )
        except Exception:
            current_app.logger.exception("LOCAL REVIEW INVALID PAYLOAD COMPLETION ERROR")
        return jsonify({"ok": False, "error": "invalid review job payload"}), 422

    return jsonify({
        "ok": True,
        "job": {
            "id": job["id"],
            "payload": payload,
            "claim_token": job["claim_token"],
        },
    }), 200


@local_review_bridge_bp.route("/complete", methods=["POST"])
def complete():
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400

    job_id = data.get("job_id")
    token = data.get("claim_token")
    status = data.get("status")
    if not _job_id_valid(job_id):
        return jsonify({"ok": False, "error": "invalid job_id"}), 400
    if not isinstance(token, str) or not token.strip() or len(token) > 256:
        return jsonify({"ok": False, "error": "invalid claim_token"}), 400
    if status not in {"REVIEWED", "NOT_RUN"}:
        return jsonify({"ok": False, "error": "invalid status"}), 400

    job = get_job(job_id)
    if job is None or job.get("job_type") != REVIEW_JOB_TYPE:
        return jsonify({"ok": False, "error": "job not found"}), 404
    if job.get("status") != "running":
        return jsonify({"ok": False, "error": "job is not running"}), 409
    expected_payload = _valid_payload(job.get("message", ""))
    if expected_payload is None:
        return jsonify({"ok": False, "error": "invalid review job payload"}), 422

    if status == "NOT_RUN":
        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1_000:
            return jsonify({"ok": False, "error": "NOT_RUN reason is required"}), 400
        result = json.dumps({
            "schema_version": 1, "status": "NOT_RUN",
            "base_sha": expected_payload["base_sha"],
            "head_sha": expected_payload["head_sha"],
            "reason": reason,
        }, ensure_ascii=False)
        success = False
        last_error = "local review not run"
    else:
        report = data.get("report")
        if not isinstance(report, dict):
            return jsonify({"ok": False, "error": "report object required"}), 400
        if report.get("schema_version") != 1 or report.get("status") != "REVIEWED":
            return jsonify({"ok": False, "error": "invalid report schema"}), 400
        if report.get("provider") != "local-fm":
            return jsonify({"ok": False, "error": "invalid provider"}), 400
        if report.get("base") != expected_payload["base_sha"] or report.get("head") != expected_payload["head_sha"]:
            return jsonify({"ok": False, "error": "report SHA mismatch"}), 409
        verdict = report.get("verdict")
        summary = report.get("summary")
        findings = report.get("findings")
        if verdict not in {"PASS", "FAIL"}:
            return jsonify({"ok": False, "error": "invalid verdict"}), 400
        if not isinstance(summary, str) or not summary.strip() or len(summary) > _MAX_SUMMARY_CHARS:
            return jsonify({"ok": False, "error": "invalid summary"}), 400
        if not _valid_findings(findings):
            return jsonify({"ok": False, "error": "invalid findings"}), 400
        if verdict == "PASS" and any(f["severity"] in {"critical", "high"} for f in findings):
            return jsonify({"ok": False, "error": "PASS conflicts with critical/high finding"}), 400
        result = json.dumps({
            "schema_version": 1, "status": "REVIEWED", "provider": "local-fm",
            "base": expected_payload["base_sha"], "head": expected_payload["head_sha"],
            "verdict": verdict, "summary": summary.strip(), "findings": findings,
        }, ensure_ascii=False)
        success = verdict == "PASS"
        last_error = None if success else "local review returned FAIL"

    try:
        updated = complete_claimed_job(
            job_id, token, success=success, result=result, last_error=last_error
        )
    except Exception:
        current_app.logger.exception("LOCAL REVIEW COMPLETE ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if not updated:
        return jsonify({"ok": False, "error": "claim token rejected"}), 409
    return jsonify({"ok": True, "status": "completed" if success else "failed"}), 200


@local_review_bridge_bp.route("/jobs/<int:job_id>/status", methods=["GET"])
def job_status(job_id: int):
    if not _authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not _job_id_valid(job_id):
        return jsonify({"ok": False, "error": "job not found"}), 404
    try:
        summary = get_job_status_summary(job_id, REVIEW_JOB_TYPE)
    except Exception:
        current_app.logger.exception("LOCAL REVIEW STATUS ERROR")
        return jsonify({"ok": False, "error": "bridge unavailable"}), 503
    if summary is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": summary}), 200
