from flask import jsonify, request
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlencode

from n8n_delegate import is_ai_app_builder_request, _call_ai_app_builder
from config import configuration
from linebot.v3.messaging import ApiClient, MessagingApi, PushMessageRequest, TextMessage

try:
    from e2e_status import StepTimer
except Exception:
    class StepTimer:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ok(self, *a, **k): pass
        def fail(self, *a, **k): pass


def _make_dashboard_url(user_id: str) -> str:
    timestamp = int(time.time())
    secret = os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""
    payload = f"{user_id}:{timestamp}"
    token = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    query = urlencode({"user_id": user_id, "ts": timestamp, "token": token})
    return f"https://line-bot-yvea.onrender.com/dashboard?{query}"


_JOB_APPROVAL_PATTERN = re.compile(
    r"(?:job\s*(?:id\s*)?[#:：]?\s*)(\d+).*?"
    r"(commit|deploy|コミット|デプロイ).*?"
    r"(承認|許可|却下|拒否)",
    re.IGNORECASE,
)


def _parse_job_approval_command(message: str):
    match = _JOB_APPROVAL_PATTERN.search(str(message))
    if not match:
        return None
    job_id = int(match.group(1))
    operation = "commit" if match.group(2).lower() in {"commit", "コミット"} else "deploy"
    decision = "approve" if match.group(3) in {"承認", "許可"} else "reject"
    return job_id, operation, decision


def _handle_job_approval(user_id: str, message: str):
    command = _parse_job_approval_command(message)
    if command is None:
        return None
    job_id, operation, decision = command
    import job_approvals
    import job_store

    job = job_store.get_job(job_id)
    if job is None:
        return "指定されたJobが見つかりません。"
    if str(job.get("user_id")) != str(user_id):
        return "このJobを操作する権限がありません。"

    if decision == "approve":
        changed = job_approvals.approve(job_id, operation, str(user_id))
        return (
            f"Job ID: {job_id} の{operation}を承認しました。Workerを再開します。"
            if changed else
            f"Job ID: {job_id} の{operation}承認は現在変更できません。"
        )

    changed = job_approvals.reject(job_id, operation)
    return (
        f"Job ID: {job_id} の{operation}を却下しました。Jobを終了します。"
        if changed else
        f"Job ID: {job_id} の{operation}却下は現在変更できません。"
    )


def _notify_new_approval(job: dict, result: dict) -> None:
    if not result.get("approval_created") or not job:
        return
    operation = result.get("operation")
    if operation not in {"commit", "deploy"}:
        return
    try:
        message = (
            f"開発Jobが{operation}承認待ちです。\n"
            f"Job ID: {job['id']}\n"
            f"LINEで「Job {job['id']} の{operation}を承認」と送ると続行します。\n"
            f"却下する場合は「Job {job['id']} の{operation}を却下」と送ってください。"
        )
        with ApiClient(configuration) as api:
            MessagingApi(api).push_message(
                PushMessageRequest(to=str(job["user_id"]), messages=[TextMessage(text=message)])
            )
    except Exception as exc:
        print("JOB APPROVAL NOTIFICATION ERROR:", exc)


def register_internal_ask_route(app, internal_push_key, generate_reply_func):
    @app.route("/internal/ask", methods=["POST"])
    def internal_ask():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or not message:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400

        if str(message).strip() == "ダッシュボード":
            dashboard_url = _make_dashboard_url(str(user_id))
            return jsonify({"ok": True, "reply": f"ダッシュボードはこちらです。\n{dashboard_url}"})

        approval_reply = _handle_job_approval(str(user_id), str(message))
        if approval_reply is not None:
            return jsonify({"ok": True, "reply": approval_reply})

        # 明示的な開発依頼は通常の会話回答に流さずJob化する。
        try:
            from development_jobs import is_development_request, enqueue_development_job
            if is_development_request(str(message)):
                job = enqueue_development_job(str(user_id), str(message))
                reply = f"開発タスクとして登録しました。\nJob ID: {job['job_id']}\n夜間に自動開発を進めます。"
                return jsonify({"ok": True, "reply": reply, "job": job})
        except Exception as exc:
            print("DEVELOPMENT JOB ENQUEUE ERROR:", exc)
            return jsonify({"ok": False, "error": f"DevelopmentJobError: {exc}"}), 500

        if is_ai_app_builder_request(message):
            handled, reply_text = _call_ai_app_builder(user_id, message)
            if handled:
                return jsonify({"ok": True, "reply": reply_text or ""})

        with StepTimer("internal_ask") as ask_timer, StepTimer("ai_mcp") as ai_timer:
            try:
                reply = generate_reply_func(user_id, message)
            except Exception as exc:
                print("INTERNAL ASK ERROR:", exc)
                ai_timer.fail(error=exc, error_location="generate_reply")
                ask_timer.fail(http_status=500, error=exc, error_location="internal_ask")
                return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
            ai_timer.ok()
            ask_timer.ok(http_status=200)
        return jsonify({"ok": True, "reply": str(reply or "")})

    @app.route("/internal/job-worker", methods=["POST"])
    def internal_job_worker():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            from job_worker import run_once
            result = run_once()
            if result:
                approval_info = result.pop("_worker_result", None) if isinstance(result, dict) else None
                _notify_new_approval(result, approval_info or {})
            return jsonify({"ok": True, "job": result})
        except Exception as exc:
            print("JOB WORKER ERROR:", exc)
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    @app.route("/internal/push", methods=["POST"])
    def internal_push():
        provided_key = request.headers.get("x-internal-key")
        if provided_key != internal_push_key:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        message = data.get("message")
        if not user_id or message is None:
            return jsonify({"ok": False, "error": "user_id and message are required"}), 400
        try:
            with ApiClient(configuration) as api:
                MessagingApi(api).push_message(PushMessageRequest(to=str(user_id), messages=[TextMessage(text=str(message))]))
            return jsonify({"ok": True})
        except Exception as exc:
            print("INTERNAL PUSH ERROR:", exc)
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return internal_ask
