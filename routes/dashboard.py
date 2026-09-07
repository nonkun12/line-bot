from functools import wraps
import hashlib
import hmac
import os
import time
from flask import Blueprint, render_template, request, jsonify, Response
from db import get_conn
from mcp_client import call_mcp_tool, parse_mcp_json_list

dashboard_bp = Blueprint("dashboard", __name__)


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
        {"WWW-Authenticate": 'Basic realm="Login Required"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def resolve_user_id(request_user_id: str | None) -> str:
    if request_user_id:
        user_id = request_user_id.strip()
        if user_id:
            if user_id == "test-user":
                return "U19391b0b93be2f4d94284361153919ce"
            return user_id

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                user_id = row[0].strip()
                if user_id:
                    if user_id == "test-user":
                        return "U19391b0b93be2f4d94284361153919ce"
                    return user_id
    except Exception as e:
        print("[DASHBOARD] Failed to fetch user_id from db:", e)

    return "U19391b0b93be2f4d94284361153919ce"


def _dashboard_secret() -> str:
    return os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""


def _make_dashboard_token(user_id: str, timestamp: int) -> str:
    secret = _dashboard_secret()
    payload = f"{user_id}:{timestamp}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _valid_dashboard_token(user_id: str, timestamp: str, token: str) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    # LINEで発行したリンクは30分有効。
    if abs(int(time.time()) - ts) > 1800:
        return False

    expected = _make_dashboard_token(user_id, ts)
    return bool(expected) and hmac.compare_digest(expected, token or "")


def _dashboard_access_allowed() -> bool:
    auth = request.authorization
    if auth and check_auth(auth.username, auth.password):
        return True

    user_id = request.args.get("user_id", "").strip()
    timestamp = request.args.get("ts", "").strip()
    token = request.args.get("token", "").strip()
    return bool(user_id and _valid_dashboard_token(user_id, timestamp, token))


def requires_dashboard_access(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _dashboard_access_allowed():
            return authenticate()
        return f(*args, **kwargs)
    return decorated


@dashboard_bp.route("/dashboard")
@requires_dashboard_access
def index():
    raw_user_id = request.args.get("user_id")
    resolved = resolve_user_id(raw_user_id)
    return render_template("dashboard.html", user_id=resolved)


@dashboard_bp.route("/api/dashboard/notes", methods=["GET"])
@requires_dashboard_access
def get_notes():
    raw_user_id = request.args.get("user_id")
    user_id = resolve_user_id(raw_user_id)
    try:
        raw_notes = call_mcp_tool("list_notes", {"user_id": user_id})
        notes = parse_mcp_json_list(raw_notes)
        return jsonify({"ok": True, "notes": notes, "user_id": user_id})
    except Exception as e:
        print("[DASHBOARD] Failed to list notes via MCP:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@dashboard_bp.route("/api/dashboard/notes", methods=["POST"])
@requires_dashboard_access
def add_note():
    data = request.get_json(silent=True) or {}
    raw_user_id = data.get("user_id") or request.args.get("user_id")
    user_id = resolve_user_id(raw_user_id)
    title = data.get("title")
    body = data.get("body")
    category = data.get("category", "一般")
    if not title or not str(title).strip():
        return jsonify({"ok": False, "error": "Title is required"}), 400
    if not body or not str(body).strip():
        return jsonify({"ok": False, "error": "Body is required"}), 400
    try:
        result = call_mcp_tool(
            "save_note",
            {
                "user_id": user_id,
                "title": str(title).strip(),
                "body": str(body).strip(),
                "category": str(category).strip() if category else "一般",
            },
        )
        return jsonify({"ok": True, "result": result, "user_id": user_id})
    except Exception as e:
        print("[DASHBOARD] Failed to save note via MCP:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@dashboard_bp.route("/api/dashboard/notes/<note_id>", methods=["DELETE"])
@requires_dashboard_access
def delete_note(note_id):
    if not note_id or not str(note_id).strip():
        return jsonify({"ok": False, "error": "Note ID is required"}), 400
    raw_user_id = request.args.get("user_id")
    user_id = resolve_user_id(raw_user_id)
    try:
        result = call_mcp_tool(
            "delete_note",
            {"user_id": user_id, "id": str(note_id).strip()},
        )
        return jsonify({"ok": True, "result": result, "user_id": user_id})
    except Exception as e:
        print("[DASHBOARD] Failed to delete note via MCP:", e)
        return jsonify({"ok": False, "error": str(e)}), 500
