"""LINE AI Secretary E2E監視ダッシュボード。

既存の /dashboard (メモ管理ダッシュボード) とは別の画面として
/status に新規実装する。認証は既存のBasic認証(DASHBOARD_USER /
DASHBOARD_PASSWORD)をそのまま再利用する。

セキュリティ: API Key / Token / Password / Secret / INTERNAL_PUSH_KEY
その他の認証情報は一切レスポンスに含めない。
"""
from functools import wraps
import os

from flask import Blueprint, render_template, request, jsonify, Response

from db import get_conn
from e2e_status import get_e2e_status, get_last_success, get_last_failure, get_error_log

e2e_bp = Blueprint("e2e_dashboard", __name__)


def check_auth(username, password):
    expected_user = os.environ.get("DASHBOARD_USER")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD")
    if not expected_user or not expected_pass:
        return False
    return username == expected_user and password == expected_pass


def authenticate():
    return Response(
        "Could not verify your access level for that URL.\n"
        "You have to login with proper credentials",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'}
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def _check_database():
    """DBに軽くクエリを投げて生死確認するだけ。内容は返さない。"""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _service_from_step(status_payload, step_key):
    for s in status_payload["steps"]:
        if s["key"] == step_key:
            if s["state"] == "ok":
                return {"status": "ok", "last_update": s.get("last_success_at")}
            if s["state"] in ("error", "stop_timeout"):
                return {
                    "status": "error",
                    "last_update": s.get("last_failure_at"),
                    "error": s.get("last_error"),
                }
            return {"status": "unknown"}
    return {"status": "unknown"}


@e2e_bp.route("/status")
@requires_auth
def status_page():
    return render_template("e2e_dashboard.html")


@e2e_bp.route("/api/e2e/status", methods=["GET"])
@requires_auth
def api_status():
    try:
        payload = get_e2e_status()
        return jsonify({"ok": True, **payload})
    except Exception as e:
        print("[E2E DASHBOARD] status error:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@e2e_bp.route("/api/e2e/services", methods=["GET"])
@requires_auth
def api_services():
    try:
        payload = get_e2e_status()

        render_configured = bool(os.environ.get("RENDER_API_KEY"))

        services = {
            "line_bot": _service_from_step(payload, "line_bot"),
            "n8n": _service_from_step(payload, "n8n_webhook"),
            "mcp": _service_from_step(payload, "ai_mcp"),
            "ai": _service_from_step(payload, "ai_mcp"),
            "render": {
                "status": "unknown" if not render_configured else "ok",
                "note": "RENDER_API_KEY未設定のため詳細確認は省略" if not render_configured else None,
            },
            "database": _check_database(),
        }
        return jsonify({"ok": True, "services": services})
    except Exception as e:
        print("[E2E DASHBOARD] services error:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@e2e_bp.route("/api/e2e/summary", methods=["GET"])
@requires_auth
def api_summary():
    try:
        return jsonify({
            "ok": True,
            "last_success": get_last_success(),
            "last_failure": get_last_failure(),
        })
    except Exception as e:
        print("[E2E DASHBOARD] summary error:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@e2e_bp.route("/api/e2e/errors", methods=["GET"])
@requires_auth
def api_errors():
    try:
        limit = request.args.get("limit", default=30, type=int)
        return jsonify({"ok": True, "errors": get_error_log(limit=limit)})
    except Exception as e:
        print("[E2E DASHBOARD] errors error:", e)
        return jsonify({"ok": False, "error": str(e)}), 500
