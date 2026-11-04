"""Authenticated transport endpoints for isolated Goal JOB workers.

These endpoints expose only typed Goal child jobs. They do not create Goals,
approve grants, clear HOLDs, merge, or deploy.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request

from flask import jsonify, request

import db
import goal_job_store
from goal_job_orchestrator import advance_goal
from goal_job_generation import generate_bounded_followup_job


def _github_run_passed(run_url: str, expected_name: str, target_sha: str) -> bool:
    """Verify a named GitHub Actions run against GitHub, never worker-supplied status."""
    match = re.fullmatch(
        r"https://github\.com/nonkun12/line-bot/actions/runs/(\d+)",
        run_url.strip() if isinstance(run_url, str) else "",
    )
    if not match:
        return False
    run_id = match.group(1)
    url = f"https://api.github.com/repos/nonkun12/line-bot/actions/runs/{run_id}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "line-bot-goal-job-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request_obj = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request_obj, timeout=8) as response:
            run = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return (
        str(run.get("id")) == run_id
        and run.get("name") == expected_name
        and run.get("head_sha") == target_sha
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    )


def _verify_exact_sha_checks(evidence: dict, produced_sha: str) -> bool:
    verification = evidence.get("verification")
    if not isinstance(verification, dict) or verification.get("target_sha") != produced_sha:
        return False
    return (
        _github_run_passed(verification.get("pytest_run_url"), "Pytest", produced_sha)
        and _github_run_passed(verification.get("review_run_url"), "Independent Code Review", produced_sha)
    )


_MEDIA_EXECUTOR_ID = "mac_local_media.v1"
_MEDIA_OPERATION = "create_audiovisual_bundle"
_MEDIA_ARTIFACT_KEYS = {
    "scenario", "music_plan", "midi", "audio_preview",
    "video_edit_decision_list", "video",
}
_MEDIA_REQUIRED_ARTIFACT_KEYS = _MEDIA_ARTIFACT_KEYS - {"video"}
_MEDIA_EVIDENCE_CHECKS = {
    "typed_local_executor_authorization",
    "scenario_validation",
    "output_confined_to_configured_root",
    "artifact_inventory_and_sha256",
    "no_publish_or_external_download",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def register_goal_job_routes(app, internal_key: str | None) -> None:
    def authorized() -> bool:
        supplied = request.headers.get("x-internal-key", "")
        return bool(internal_key and supplied and hmac.compare_digest(str(supplied), str(internal_key)))

    @app.route("/internal/media-jobs/claim", methods=["POST"])
    def claim_local_media_job():
        if not authorized():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            job = db.claim_pending_media_goal_child_job(_MEDIA_EXECUTOR_ID)
            if job is None:
                return jsonify({"ok": True, "claimed": False}), 200
            try:
                payload = goal_job_store.authorize_claimed_media_job(
                    job, _MEDIA_EXECUTOR_ID, _MEDIA_OPERATION
                )
            except Exception as exc:
                goal_job_store.complete_claimed_child_job(
                    job["id"], job["claim_token"], success=False,
                    last_error=f"media authorization failed: {type(exc).__name__}",
                )
                app.logger.warning("Local media Goal authorization rejected: job_id=%s", job["id"])
                return jsonify({"ok": False, "error": "media job authorization failed"}), 403
            return jsonify({
                "ok": True,
                "claimed": True,
                "job": {
                    "id": job["id"],
                    "job_type": job["job_type"],
                    "claim_token": job["claim_token"],
                    "payload": payload,
                },
                "lease_seconds": 1800,
            }), 200
        except Exception:
            app.logger.exception("Local media Goal claim failed")
            return jsonify({"ok": False, "error": "media job claim failed"}), 500

    @app.route("/internal/media-jobs/hold", methods=["POST"])
    def hold_local_media_job():
        if not authorized():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        claim_token = data.get("claim_token")
        reason = data.get("reason")
        if type(job_id) is not int or job_id <= 0:
            return jsonify({"ok": False, "error": "job_id must be a positive integer"}), 400
        if not isinstance(claim_token, str) or len(claim_token) < 20:
            return jsonify({"ok": False, "error": "claim_token is invalid"}), 400
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            return jsonify({"ok": False, "error": "a bounded HOLD reason is required"}), 400
        claimed = db.get_job(job_id)
        if not claimed or claimed.get("status") != "running" or claimed.get("claim_token") != claim_token:
            return jsonify({"ok": False, "error": "claim is stale or already completed"}), 409
        try:
            goal_job_store.authorize_claimed_media_job(
                claimed, _MEDIA_EXECUTOR_ID, _MEDIA_OPERATION
            )
            held = db.hold_claimed_goal_child_job(job_id, claim_token, reason)
            if not held:
                return jsonify({"ok": False, "error": "claim is stale or already completed"}), 409
            return jsonify({"ok": True, "held": True, "status": "HOLD"}), 200
        except PermissionError:
            return jsonify({"ok": False, "error": "media Goal authorization failed"}), 403
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            app.logger.exception("Local media Goal HOLD failed")
            return jsonify({"ok": False, "error": "media job HOLD failed"}), 500

    @app.route("/internal/media-jobs/complete", methods=["POST"])
    def complete_local_media_job():
        if not authorized():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        claim_token = data.get("claim_token")
        result = data.get("result")
        evidence = data.get("evidence")
        if type(job_id) is not int or job_id <= 0:
            return jsonify({"ok": False, "error": "job_id must be a positive integer"}), 400
        if not isinstance(claim_token, str) or len(claim_token) < 20:
            return jsonify({"ok": False, "error": "claim_token is invalid"}), 400
        if not isinstance(result, str) or not result.strip() or len(result) > 20000:
            return jsonify({"ok": False, "error": "result is invalid"}), 400
        if not isinstance(evidence, dict) or not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
            return jsonify({"ok": False, "error": "evidence checks are required"}), 400
        try:
            receipt = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return jsonify({"ok": False, "error": "media receipt must be JSON"}), 400
        artifact_hashes = receipt.get("artifact_sha256") if isinstance(receipt, dict) else None
        evidence_hashes = evidence.get("artifact_sha256")
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema_version") != "mac-local-media-receipt.v1"
            or receipt.get("executor") != _MEDIA_EXECUTOR_ID
            or receipt.get("operation") != _MEDIA_OPERATION
            or receipt.get("goal_job_id") != job_id
            or receipt.get("status") != "draft"
            or receipt.get("publication") != "not_performed"
            or not isinstance(artifact_hashes, dict)
            or set(artifact_hashes) != _MEDIA_REQUIRED_ARTIFACT_KEYS
            or receipt.get("video_render_status") != "not_rendered"
            or any(not isinstance(value, str) or not _SHA256_RE.fullmatch(value) for value in artifact_hashes.values())
            or receipt.get("idempotency_key") != hashlib.sha256(
                f"{_MEDIA_EXECUTOR_ID}:{job_id}".encode()
            ).hexdigest()
            or evidence_hashes != artifact_hashes
            or not isinstance(evidence.get("receipt_sha256"), str)
            or not _SHA256_RE.fullmatch(evidence["receipt_sha256"])
            or evidence.get("receipt_sha256") != hashlib.sha256((result + "\n").encode("utf-8")).hexdigest()
            or evidence.get("executor") != _MEDIA_EXECUTOR_ID
            or evidence.get("goal_job_id") != job_id
        ):
            return jsonify({"ok": False, "error": "media receipt or artifact hashes failed validation"}), 400
        if (
            {check.get("name") for check in evidence["checks"] if isinstance(check, dict)}
            != _MEDIA_EVIDENCE_CHECKS
            or not all(
                isinstance(check, dict)
                and check.get("name") in _MEDIA_EVIDENCE_CHECKS
                and check.get("status") == "PASS"
                and check.get("source") == _MEDIA_EXECUTOR_ID
                for check in evidence["checks"]
            )
        ):
            return jsonify({"ok": False, "error": "all media evidence checks must be executor-sourced PASS"}), 400
        try:
            claimed = db.get_job(job_id)
            if not claimed or claimed.get("status") != "running" or claimed.get("claim_token") != claim_token:
                return jsonify({"ok": False, "error": "claim is stale or already completed"}), 409
            goal_job_store.authorize_claimed_media_job(
                claimed, _MEDIA_EXECUTOR_ID, _MEDIA_OPERATION
            )
            completed = goal_job_store.complete_claimed_child_job(
                job_id, claim_token, success=True, result=result, evidence=evidence
            )
            if not completed:
                return jsonify({"ok": False, "error": "claim is stale or already completed"}), 409
            continuation = {"decision": "NOT_STARTED"}
            try:
                goal_id = goal_job_store.get_goal_id_for_child_job(job_id)
                if goal_id:
                    criterion_results = goal_job_store.evaluate_completed_goal_criteria(goal_id)
                    goal_job_store.update_goal_evidence(goal_id, criterion_results)
                    continuation = advance_goal(
                        goal_id, job_generator=generate_bounded_followup_job
                    )
            except Exception as exc:
                app.logger.exception("Media Goal continuation failed after durable completion")
                continuation = {
                    "decision": "HOLD",
                    "reason": "goal_continuation_failed",
                    "error_type": type(exc).__name__,
                }
            return jsonify({
                "ok": True, "completed": True, "success": True,
                "continuation": continuation,
            }), 200
        except PermissionError:
            return jsonify({"ok": False, "error": "media Goal authorization failed"}), 403
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            app.logger.exception("Local media Goal completion failed")
            return jsonify({"ok": False, "error": "media job completion failed"}), 500

    @app.route("/internal/goal-jobs/claim", methods=["POST"])
    def claim_goal_job():
        if not authorized():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        if job_id is not None and (type(job_id) is not int or job_id <= 0):
            return jsonify({"ok": False, "error": "job_id must be a positive integer"}), 400
        try:
            job = db.claim_goal_child_job(job_id) if job_id is not None else db.claim_pending_job_by_type("goal_child")
            if job is None:
                return jsonify({"ok": True, "claimed": False}), 200
            try:
                payload = goal_job_store.authorize_claimed_job(job)
            except Exception as exc:
                goal_job_store.complete_claimed_child_job(
                    job["id"], job["claim_token"], success=False,
                    last_error=f"authorization failed: {type(exc).__name__}",
                )
                app.logger.warning("Goal child authorization rejected: job_id=%s", job["id"])
                return jsonify({"ok": False, "error": "goal job authorization failed"}), 403
            return jsonify({
                "ok": True,
                "claimed": True,
                "job": {
                    "id": job["id"],
                    "job_type": job["job_type"],
                    "claim_token": job["claim_token"],
                    "payload": payload,
                },
            }), 200
        except Exception:
            app.logger.exception("Goal child claim failed")
            return jsonify({"ok": False, "error": "goal job claim failed"}), 500

    @app.route("/internal/goal-jobs/complete", methods=["POST"])
    def complete_goal_job():
        if not authorized():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        claim_token = data.get("claim_token")
        success = data.get("success")
        result = data.get("result")
        evidence = data.get("evidence")
        if type(job_id) is not int or job_id <= 0:
            return jsonify({"ok": False, "error": "job_id must be a positive integer"}), 400
        if not isinstance(claim_token, str) or not claim_token:
            return jsonify({"ok": False, "error": "claim_token is required"}), 400
        if type(success) is not bool:
            return jsonify({"ok": False, "error": "success must be boolean"}), 400
        if success:
            if not isinstance(result, str) or not result.strip() or len(result) > 20000:
                return jsonify({"ok": False, "error": "successful result is invalid"}), 400
            if not isinstance(evidence, dict) or not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
                return jsonify({"ok": False, "error": "successful completion requires evidence checks"}), 400
            if not all(isinstance(check, dict) and check.get("status") == "PASS" for check in evidence["checks"]):
                success = False
            if success:
                verification = evidence.get("verification")
                produced_sha = evidence.get("produced_sha")
                if (
                    not isinstance(verification, dict)
                    or not isinstance(produced_sha, str)
                    or len(produced_sha) not in {40, 64}
                    or any(ch not in "0123456789abcdef" for ch in produced_sha.lower())
                    or verification.get("target_sha") != produced_sha
                    or verification.get("pytest_status") != "PASS"
                    or verification.get("review_status") != "PASS"
                    or not _verify_exact_sha_checks(evidence, produced_sha)
                ):
                    return jsonify({"ok": False, "error": "GitHub-confirmed exact-SHA pytest and review success is required"}), 400
        try:
            completed = goal_job_store.complete_claimed_child_job(
                job_id,
                claim_token,
                success=success,
                result=result if success else None,
                last_error=None if success else str(data.get("last_error") or "worker reported failure")[:2000],
                evidence=evidence if success else None,
            )
            if not completed:
                return jsonify({"ok": False, "error": "claim is stale or already completed"}), 409

            continuation = {"decision": "NOT_STARTED"}
            try:
                goal_id = goal_job_store.get_goal_id_for_child_job(job_id)
                if goal_id:
                    criterion_results = goal_job_store.evaluate_completed_goal_criteria(goal_id)
                    goal_job_store.update_goal_evidence(goal_id, criterion_results)
                    continuation = advance_goal(
                        goal_id,
                        job_generator=generate_bounded_followup_job,
                    )
            except Exception as exc:
                # Completion is already durable. Preserve it and expose a
                # continuation HOLD rather than returning a false worker failure.
                app.logger.exception("Goal continuation failed after child completion")
                continuation = {
                    "decision": "HOLD",
                    "reason": "goal_continuation_failed",
                    "error_type": type(exc).__name__,
                }
            return jsonify({
                "ok": True,
                "completed": True,
                "success": success,
                "continuation": continuation,
            }), 200
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            app.logger.exception("Goal child completion failed")
            return jsonify({"ok": False, "error": "goal job completion failed"}), 500


__all__ = ["register_goal_job_routes"]
