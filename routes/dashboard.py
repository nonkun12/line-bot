from functools import wraps
import hashlib
import hmac
import json
import os
import time
from flask import Blueprint, render_template, request, jsonify, Response
from db import get_conn
from mcp_client import call_mcp_tool, parse_mcp_json_list
from e2e_status import get_e2e_status

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


def resolve_user_id(request_user_id: str | None) -> str:
    if request_user_id:
        user_id = request_user_id.strip()
        if user_id:
            if user_id == "test-user":
                return "U19391b0b93be2f4d94284361153919ce"
            return user_id
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT user_id FROM messages ORDER BY id DESC LIMIT 1").fetchone()
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


def _oracle_secret() -> str:
    return os.environ.get("ORACLE_STATUS_SECRET", "")


def _verify_oracle_signature(raw_body: bytes, signature: str) -> bool:
    secret = _oracle_secret()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _init_oracle_status_table():
    try:
        with get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oracle_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    received_at REAL NOT NULL
                )
            """)
    except Exception as e:
        print("[DASHBOARD] oracle_status init error:", e)


_init_oracle_status_table()


@dashboard_bp.route("/dashboard")
@requires_dashboard_access
def index():
    raw_user_id = request.args.get("user_id")
    resolved = resolve_user_id(raw_user_id)
    return render_template("dashboard.html", user_id=resolved)


@dashboard_bp.route("/api/dashboard/notes", methods=["GET"])
@requires_dashboard_access
def get_notes():
    user_id = resolve_user_id(request.args.get("user_id"))
    try:
        notes = parse_mcp_json_list(call_mcp_tool("list_notes", {"user_id": user_id}))
        return jsonify({"ok": True, "notes": notes, "user_id": user_id})
    except Exception as e:
        print("[DASHBOARD] Failed to list notes via MCP:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@dashboard_bp.route("/api/dashboard/notes", methods=["POST"])
@requires_dashboard_access
def add_note():
    data = request.get_json(silent=True) or {}
    user_id = resolve_user_id(data.get("user_id") or request.args.get("user_id"))
    title, body = data.get("title"), data.get("body")
    category = data.get("category", "一般")
    if not title or not str(title).strip():
        return jsonify({"ok": False, "error": "Title is required"}), 400
    if not body or not str(body).strip():
        return jsonify({"ok": False, "error": "Body is required"}), 400
    try:
        result = call_mcp_tool("save_note", {"user_id": user_id, "title": str(title).strip(), "body": str(body).strip(), "category": str(category).strip() if category else "一般"})
        return jsonify({"ok": True, "result": result, "user_id": user_id})
    except Exception as e:
        print("[DASHBOARD] Failed to save note via MCP:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@dashboard_bp.route("/api/dashboard/notes/<note_id>", methods=["DELETE"])
@requires_dashboard_access
def delete_note(note_id):
    if not note_id or not str(note_id).strip():
        return jsonify({"ok": False, "error": "Note ID is required"}), 400
    user_id = resolve_user_id(request.args.get("user_id"))
    try:
        result = call_mcp_tool("delete_note", {"user_id": user_id, "id": str(note_id).strip()})
        return jsonify({"ok": True, "result": result, "user_id": user_id})
    except Exception as e:
        print("[DASHBOARD] Failed to delete note via MCP:", e)
        return jsonify({"ok": False, "error": str(e), "user_id": user_id}), 500


@dashboard_bp.route("/internal/oracle/status", methods=["POST"])
def receive_oracle_status():
    raw = request.get_data()
    signature = request.headers.get("X-Oracle-Signature", "")
    if not _verify_oracle_signature(raw, signature):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        received_at = time.time()
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO oracle_status(id, payload, received_at) VALUES(1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, received_at=excluded.received_at
            """, (json.dumps(payload, ensure_ascii=False), received_at))
        return jsonify({"ok": True})
    except Exception as e:
        print("[DASHBOARD] Invalid oracle status:", e)
        return jsonify({"ok": False, "error": "invalid payload"}), 400


@dashboard_bp.route("/api/dashboard/system", methods=["GET"])
@requires_dashboard_access
def system_status():
    now = time.time()
    result = {"ok": True, "render": {"status": "online", "timestamp": now}}

    try:
        with get_conn() as conn:
            row = conn.execute("SELECT payload, received_at FROM oracle_status WHERE id=1").fetchone()
        if row:
            payload = json.loads(row[0])
            age = max(0, now - float(row[1]))
            if age <= 90:
                state = "online"
            elif age <= 300:
                state = "stale"
            else:
                state = "offline"
            result["oracle"] = {"status": state, "age_sec": round(age), "last_seen": row[1], "data": payload}
        else:
            result["oracle"] = {"status": "offline", "age_sec": None, "data": None}
    except Exception as e:
        result["oracle"] = {"status": "error", "error": str(e)}

    # E2E history is independent from the dashboard's direct health checks.
    try:
        e2e = get_e2e_status()
        result["e2e"] = e2e
        step_map = {s["key"]: s for s in e2e.get("steps", [])}
        oracle_n8n = result.get("oracle", {}).get("data", {}).get("docker", {}).get("n8n", {})
        oracle_n8n_status = str(oracle_n8n.get("status", "")).lower()
        n8n_live = bool(oracle_n8n) and oracle_n8n_status in {"running", "up", "restarting"}
        result["services"] = {
            "line_bot": "online",
            "n8n": "online" if n8n_live or step_map.get("n8n_webhook", {}).get("state") == "ok" else "unknown",
            "ai_mcp": "unknown",
        }
    except Exception as e:
        result["e2e"] = {"error": str(e)}
        result["services"] = {"line_bot": "online", "n8n": "unknown", "ai_mcp": "unknown"}

    user_id = resolve_user_id(request.args.get("user_id"))
    try:
        notes = parse_mcp_json_list(call_mcp_tool("list_notes", {"user_id": user_id}))
        result["notes"] = {"status": "ok", "count": len(notes), "latest": notes[:5]}
    except Exception as e:
        result["notes"] = {"status": "error", "error": str(e)}

    try:
        reminders = parse_mcp_json_list(call_mcp_tool("list_reminders", {"user_id": user_id}))
        result["reminders"] = {"status": "ok", "count": len(reminders), "latest": reminders[:5]}
    except Exception as e:
        result["reminders"] = {"status": "error", "error": str(e)}

    if result.get("notes", {}).get("status") == "ok" and result.get("reminders", {}).get("status") == "ok":
        result["services"]["ai_mcp"] = "online"

    return jsonify(result)
