"""Authenticated transport endpoints for isolated Goal JOB workers.

These endpoints expose only typed Goal child jobs. They do not create Goals,
approve grants, clear HOLDs, merge, or deploy.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import urllib.error
import urllib.request

from flask import jsonify, request

import db
import goal_job_store


def _github_run_passed(run_url: str, expected_name: str, target_sha: str) -> bool:
    """Verify a named GitHub Actions run against GitHub, never worker-supplied status."""
    match = re.fullmatch(
        r"https://github\\.com/nonkun12/line-bot/actions/runs/(\\d+)",
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
        and _github_run_passed(verification.get("review_run_url"), "AI Code Review", produced_sha)
    )


def register_goal_job_routes(app, internal_key: str | None) -> None:
    def authorized() -> bool:
        supplied = request.headers.get("x-internal-key", "")
        return bool(internal_key and supplied and hmac.compare_digest(str(supplied), str(internal_key)))

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
            return jsonify({"ok": True, "completed": True, "success": success}), 200
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            app.logger.exception("Goal child completion failed")
            return jsonify({"ok": False, "error": "goal job completion failed"}), 500


__all__ = ["register_goal_job_routes"]
