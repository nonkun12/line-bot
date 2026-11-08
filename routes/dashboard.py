from functools import wraps
from datetime import datetime, timezone
import httpx
import hashlib
import hmac
import json
import os
import re
import time
from flask import Blueprint, current_app, render_template, request, jsonify, Response
from db import get_conn
from mcp_client import call_mcp_tool, parse_mcp_json_list
from e2e_status import get_e2e_status
from core.distributed_agent_catalog import DISTRIBUTED_AGENT_CATALOG
from core.specialist_gate import is_specialist_approved
from graph.core_registry import build_core_agent_registry
from agents.stocks.node import StocksAgent
from agents.stocks.selection import analyze_prices

dashboard_bp = Blueprint("dashboard", __name__)


def check_auth(username, password):
    expected_user = os.environ.get("DASHBOARD_USER")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD")
    if not expected_user or not expected_pass:
        return False
    return hmac.compare_digest(str(username or ""), str(expected_user)) and hmac.compare_digest(str(password or ""), str(expected_pass))


def authenticate():
    return Response("Could not verify your access level for that URL.\nYou have to login with proper credentials", 401, {"WWW-Authenticate": 'Basic realm="Login Required"'})


def resolve_user_id(request_user_id: str | None) -> str | None:
    if request_user_id:
        user_id = str(request_user_id).strip()
        if user_id and user_id != "test-user":
            return user_id
    owner = os.environ.get("DASHBOARD_OWNER_USER_ID", "").strip()
    return owner or None


def _dashboard_secret() -> str:
    return os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""


def _make_dashboard_token(user_id: str, timestamp: int) -> str:
    secret = _dashboard_secret()
    if not secret:
        return ""
    payload = f"{user_id}:{timestamp}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _valid_dashboard_token(user_id: str, timestamp: str, token: str) -> bool:
    if not _dashboard_secret():
        return False
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


def _init_orca_status_table():
    try:
        with get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orca_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    received_at REAL NOT NULL
                )
            """)
    except Exception:
        current_app.logger.exception("DASHBOARD ORCA STATUS TABLE INIT ERROR")


_init_orca_status_table()


def _require_user_id(user_id):
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400
    return None


def _internal_error(logger, message, *, with_user_id=False, user_id=None):
    logger.exception(message)
    payload = {"ok": False, "error": "internal server error"}
    if with_user_id and user_id:
        payload["user_id"] = user_id
    return jsonify(payload), 500


def _get_oracle_n8n_status(oracle_data):
    """Safely extract n8n status from an optional Oracle status payload."""
    if not isinstance(oracle_data, dict):
        return ""
    docker = oracle_data.get("docker")
    if not isinstance(docker, dict):
        return ""
    n8n = docker.get("n8n")
    if not isinstance(n8n, dict):
        return ""
    return str(n8n.get("status", "")).lower()


@dashboard_bp.route("/dashboard")
@requires_dashboard_access
def index():
    resolved = resolve_user_id(request.args.get("user_id"))
    error = _require_user_id(resolved)
    if error:
        return error
    return render_template("dashboard.html", user_id=resolved)


@dashboard_bp.route("/api/dashboard/notes", methods=["GET"])
@requires_dashboard_access
def get_notes():
    user_id = resolve_user_id(request.args.get("user_id"))
    error = _require_user_id(user_id)
    if error:
        return error
    try:
        notes = parse_mcp_json_list(call_mcp_tool("list_notes", {"user_id": user_id}))
        return jsonify({"ok": True, "notes": notes, "user_id": user_id})
    except Exception:
        return _internal_error(current_app.logger, "DASHBOARD LIST NOTES ERROR", with_user_id=True, user_id=user_id)


@dashboard_bp.route("/api/dashboard/notes", methods=["POST"])
@requires_dashboard_access
def add_note():
    data = request.get_json(silent=True) or {}
    user_id = resolve_user_id(data.get("user_id") or request.args.get("user_id"))
    error = _require_user_id(user_id)
    if error:
        return error
    title, body = data.get("title"), data.get("body")
    category = data.get("category", "一般")
    if not title or not str(title).strip():
        return jsonify({"ok": False, "error": "Title is required"}), 400
    if not body or not str(body).strip():
        return jsonify({"ok": False, "error": "Body is required"}), 400
    try:
        result = call_mcp_tool("save_note", {"user_id": user_id, "title": str(title).strip(), "body": str(body).strip(), "category": str(category).strip() if category else "一般"})
        return jsonify({"ok": True, "result": result, "user_id": user_id})
    except Exception:
        return _internal_error(current_app.logger, "DASHBOARD SAVE NOTE ERROR", with_user_id=True, user_id=user_id)


@dashboard_bp.route("/api/dashboard/notes/<note_id>", methods=["DELETE"])
@requires_dashboard_access
def delete_note(note_id):
    if not note_id or not str(note_id).strip():
        return jsonify({"ok": False, "error": "Note ID is required"}), 400
    user_id = resolve_user_id(request.args.get("user_id"))
    error = _require_user_id(user_id)
    if error:
        return error
    try:
        result = call_mcp_tool("delete_note", {"user_id": user_id, "id": str(note_id).strip()})
        return jsonify({"ok": True, "result": result, "user_id": user_id})
    except Exception:
        return _internal_error(current_app.logger, "DASHBOARD DELETE NOTE ERROR", with_user_id=True, user_id=user_id)


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
    except Exception:
        current_app.logger.exception("DASHBOARD INVALID ORACLE STATUS")
        return jsonify({"ok": False, "error": "invalid payload"}), 400


def _orca_snapshot_timestamp(value):
    from datetime import datetime, timezone
    if not isinstance(value, str) or not value.strip():
        raise ValueError("captured_at is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("captured_at timezone is required")
    captured = parsed.timestamp()
    age = time.time() - captured
    if age < -60 or age > 300:
        raise ValueError("snapshot timestamp outside accepted window")
    return captured


_ORCA_ALLOWED_FIELDS = {
    "tasks": {"id", "task_id", "status", "state", "stage", "created_at", "updated_at", "dispatch_id", "worker_id", "stream_key"},
    "dispatches": {"id", "dispatch_id", "task_id", "status", "state", "stage", "created_at", "updated_at", "worker_id", "stream_key"},
    "workers": {"id", "worker_id", "dispatch_id", "task_id", "status", "state", "stage", "addressable", "exactWorker", "created_at", "updated_at", "stream_key"},
}
_ORCA_STREAM_KEYS = {"main_star_night", "side_task_supply", "side_media_ai", "side_self_improvement", "side_line_full_control", "side_core_vocabulary"}


def _sanitize_orca_payload(payload):
    captured = _orca_snapshot_timestamp(payload.get("captured_at"))
    clean = {"captured_at": datetime.fromtimestamp(captured, tz=timezone.utc).isoformat(),
             "run_id": str(payload.get("run_id") or "")[:100]}
    for group, allowed in _ORCA_ALLOWED_FIELDS.items():
        items = payload.get(group, [])
        if not isinstance(items, list) or len(items) > 100 or any(not isinstance(item, dict) for item in items):
            raise ValueError(f"invalid {group} collection")
        clean[group] = [{k: v for k, v in item.items() if k in allowed
                         and isinstance(v, (str, int, float, bool)) and len(str(v)) <= 300}
                        for item in items]
    streams = payload.get("streams", [])
    if not isinstance(streams, list) or len(streams) > 5:
        raise ValueError("invalid streams collection")
    clean["streams"] = []
    for item in streams:
        if not isinstance(item, dict) or item.get("key") not in _ORCA_STREAM_KEYS:
            raise ValueError("invalid stream record")
        clean["streams"].append({
            "key": item["key"], "label": str(item.get("label") or "")[:80],
            "kind": "main" if item.get("kind") == "main" else "side",
            "status": "observed" if item.get("status") == "observed" else "unknown",
            "task_count": max(0, min(int(item.get("task_count", 0)), 100)),
            "dispatch_count": max(0, min(int(item.get("dispatch_count", 0)), 100)),
            "worker_count": max(0, min(int(item.get("worker_count", 0)), 100)),
            "evidence": "matched_runtime_records" if item.get("evidence") == "matched_runtime_records" else "no_matching_stream_metadata",
        })
    return clean, captured


@dashboard_bp.route("/internal/orca/status", methods=["POST"])
def receive_orca_status():
    raw = request.get_data(cache=False)
    if len(raw) > 65536:
        return jsonify({"ok": False, "error": "payload_too_large"}), 413
    secret = os.environ.get("ORCA_STATUS_SECRET", "")
    signature = request.headers.get("X-Orca-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest() if secret else ""
    if not expected or not signature or not hmac.compare_digest(expected, signature):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        clean, captured_at = _sanitize_orca_payload(payload)
        with get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM orca_status WHERE id=1").fetchone()
            if row:
                previous = json.loads(row[0])
                previous_at = _orca_snapshot_timestamp_allow_stale(previous.get("captured_at"))
                if captured_at <= previous_at:
                    conn.rollback()
                    return jsonify({"ok": False, "error": "snapshot_out_of_order"}), 409
            received_at = time.time()
            conn.execute("""INSERT INTO orca_status(id, payload, received_at) VALUES(1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, received_at=excluded.received_at""",
                (json.dumps(clean, ensure_ascii=False), received_at))
            conn.commit()
        return jsonify({"ok": True, "received_at": received_at})
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400
    except Exception:
        current_app.logger.exception("DASHBOARD ORCA STATUS WRITE ERROR")
        return jsonify({"ok": False, "error": "storage_error"}), 500


def _orca_snapshot_timestamp_allow_stale(value):
    from datetime import datetime
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp timezone missing")
    return parsed.timestamp()


@dashboard_bp.route("/api/dashboard/orca", methods=["GET"])
@requires_dashboard_access
def orca_status():
    now = time.time()
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT payload, received_at FROM orca_status WHERE id=1").fetchone()
        if not row:
            return jsonify({"ok": True, "status": "offline", "age_sec": None,
                            "tasks": [], "dispatches": [], "workers": [], "streams": []})
        payload = json.loads(row[0])
        captured = _orca_snapshot_timestamp_allow_stale(payload.get("captured_at"))
        age = max(0, now - captured)
        status = "online" if age <= 90 else ("stale" if age <= 300 else "offline")
        return jsonify({"ok": True, "status": status, "age_sec": round(age),
                        "received_at": row[1], "captured_at": payload.get("captured_at"),
                        "tasks": payload.get("tasks", []), "dispatches": payload.get("dispatches", []),
                        "workers": payload.get("workers", []), "streams": payload.get("streams", [])})
    except Exception:
        current_app.logger.exception("DASHBOARD ORCA STATUS READ ERROR")
        return jsonify({"ok": False, "status": "error"}), 500


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
            state = "online" if age <= 90 else ("stale" if age <= 300 else "offline")
            result["oracle"] = {"status": state, "age_sec": round(age), "last_seen": row[1], "data": payload}
        else:
            result["oracle"] = {"status": "offline", "age_sec": None, "data": None}
    except Exception:
        current_app.logger.exception("DASHBOARD SYSTEM ORACLE ERROR")
        result["oracle"] = {"status": "error"}
    try:
        e2e = get_e2e_status()
        result["e2e"] = e2e
        step_map = {s["key"]: s for s in e2e.get("steps", [])}
        oracle_n8n_status = _get_oracle_n8n_status(result.get("oracle", {}).get("data"))
        n8n_live = oracle_n8n_status in {"running", "up", "restarting"}
        result["services"] = {"line_bot": "online", "n8n": "online" if n8n_live or step_map.get("n8n_webhook", {}).get("state") == "ok" else "unknown", "ai_mcp": "unknown"}
    except Exception:
        current_app.logger.exception("DASHBOARD SYSTEM E2E ERROR")
        result["e2e"] = {"error": "internal server error"}
        result["services"] = {"line_bot": "online", "n8n": "unknown", "ai_mcp": "unknown"}
    user_id = resolve_user_id(request.args.get("user_id"))
    error = _require_user_id(user_id)
    if error:
        return error
    # Do not wake the on-demand MCP service from the dashboard heartbeat.
    # Notes/reminders are fetched only by explicit user actions. Keeping this
    # endpoint MCP-free prevents a browser poll from creating cold-start/429 bursts.
    result["notes"] = {"status": "unknown", "count": None, "latest": []}
    result["reminders"] = {"status": "unknown", "count": None, "latest": []}

    registry = build_core_agent_registry()
    registered_names = set(registry.names())

    def specialist_status(descriptor):
        return "online" if (
            descriptor.agent_name in registered_names
            and is_specialist_approved(descriptor.role)
        ) else "planned"

    result["features"] = {
        "management_ai": {
            "status": "online",
            "label": "統合AI / Management",
            "detail": "タスク分解・専門AIへの配分・結果回収・有界再指示",
        },
    }
    for descriptor in DISTRIBUTED_AGENT_CATALOG:
        status = specialist_status(descriptor)
        result["features"][descriptor.key] = {
            "status": status,
            "label": descriptor.label,
            "detail": descriptor.detail,
        }

    specialists = [
        {
            "key": descriptor.key,
            "label": descriptor.label,
            "status": specialist_status(descriptor),
            "role": descriptor.detail,
        }
        for descriptor in DISTRIBUTED_AGENT_CATALOG
    ]
    distributed_status = "online" if all(item["status"] == "online" for item in specialists) else "planned"
    result["distributed_ai"] = {
        "status": distributed_status,
        "architecture": "management -> specialists -> result collection -> bounded re-planning",
        "message_bus": "enabled",
        "specialists": specialists,
    }
    return jsonify(result)


@dashboard_bp.route("/api/dashboard/loop", methods=["GET"])
@requires_dashboard_access
def autonomous_loop_status():
    """Expose configured autonomous-loop controls without claiming unverified runtime activity."""
    return jsonify({
        "ok": True,
        "loop": {
            "status": "configured",
            "schedule_jst": ["04:30", "10:30", "16:30", "22:30"],
            "frequency_per_day": 4,
            "target_cadence": "hourly",
            "target_cadence_verified": False,
            "streams": [
                {"key": "main_star_night", "kind": "main", "label": "本線：STAR-NIGHT", "status": "in_development", "cadence": "hourly_target", "detail": "物語・シナリオ・音楽・映像の継続制作。毎時実行は未検証。", "related_prs": [1285]},
                {"key": "side_task_supply", "kind": "side", "label": "サイド1：分散Loop・タスク枯渇対策", "status": "in_development", "cadence": "hourly_target", "detail": "候補補充・重複防止・失敗復旧候補。毎時実行は未検証。", "related_prs": [1276]},
                {"key": "side_media_ai", "kind": "side", "label": "サイド2：映像・音楽AI", "status": "in_development", "cadence": "hourly_target", "detail": "映像・音楽の生成と品質改善。毎時実行・実稼働は未検証。", "related_prs": []},
                {"key": "side_self_improvement", "kind": "side", "label": "サイド3：自己改善AI", "status": "in_development", "cadence": "hourly_target", "detail": "失敗分析・改善候補・開発効率改善。安全ゲートは維持。", "related_prs": [1278]},
                {"key": "side_line_full_control", "kind": "side", "label": "サイド4：LINE全指示化", "status": "in_development", "cadence": "hourly_target", "detail": "LINEから4サイドを含む開発指示を受付。読み取り依頼は開発へ送らない。", "related_prs": [1282, 1283, 1284]},
                {"key": "side_core_vocabulary", "kind": "side", "label": "サイド5：英単語コア語彙", "status": "in_development", "cadence": "every_5_hours_target", "detail": "既存のコアイメージ辞書を再利用し、レビュー済みユニーク語数を1,000語へ拡張。5時間ごとの実行はCI証跡で確認するまで未検証。", "related_prs": [368]}
            ],
            "manual_run_available": True,
            "manual_default_tasks": 1,
            "max_tasks_per_run": 4,
            "concurrency_cancel_in_progress": False,
            "auto_apply_patch": False,
            "auto_deploy": False,
            "fail_closed": True,
            "sheets_audit": True,
            "runtime_telemetry": "github_actions",
            "last_run": _github_loop_runs(),
            "note": "未取得のGitHub Actions実行を成功・実行済みとは表示しません。",
        },
        "safety": {
            "auto_merge": False,
            "auto_deploy": False,
            "self_improvement_policy": True,
            "hermes_role": "adviser",
            "hermes_is_auxiliary": True,
        },
        "hand_sign": {
            "camera_smoke_test": "implemented",
            "camera_upload": False,
            "camera_storage": False,
            "next_phase": "hand-sign recognition",
        },
    })


def _github_loop_runs():
    """Read-only GitHub Actions telemetry for the autonomous loop."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return {"status": "unavailable", "reason": "GITHUB_TOKEN not configured"}
    url = "https://api.github.com/repos/nonkun12/line-bot/actions/workflows/distributed-autonomous-loop.yml/runs"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url, headers=headers, params={"per_page": 5})
        if response.status_code != 200:
            return {"status": "unavailable", "reason": f"github_api_{response.status_code}"}
        payload = response.json()
        runs = []
        for run in payload.get("workflow_runs", [])[:5]:
            runs.append({
                "id": run.get("id"),
                "run_number": run.get("run_number"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "event": run.get("event"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "name": run.get("name"),
                "display_title": run.get("display_title"),
                "head_sha": run.get("head_sha"),
                "run_attempt": run.get("run_attempt"),
                "workflow_id": run.get("workflow_id"),
                "html_url": run.get("html_url"),
            })
        return {"status": "ok", "runs": runs}
    except Exception:
        current_app.logger.exception("DASHBOARD GITHUB LOOP TELEMETRY ERROR")
        return {"status": "unavailable", "reason": "github_api_error"}


_STOCK_DASHBOARD_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,9}$")
_STOCK_DASHBOARD_MAX_TICKERS = 6


def _normalize_stock_dashboard_tickers(raw):
    if isinstance(raw, str):
        values = re.split(r"[\s,、]+", raw)
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    tickers = []
    for value in values:
        text = str(value or "").strip().upper()
        if not text:
            continue
        ticker = StocksAgent.normalize_ticker(text)
        if not _STOCK_DASHBOARD_TICKER_RE.fullmatch(ticker):
            continue
        if ticker not in tickers:
            tickers.append(ticker)
        if len(tickers) >= _STOCK_DASHBOARD_MAX_TICKERS:
            break
    return tickers


def _analyze_stock_dashboard_ticker(ticker):
    quote = StocksAgent._fetch_quote(ticker)
    history = StocksAgent._fetch_history(ticker)
    indicators = analyze_prices(history)
    return {
        "ticker": StocksAgent._display_ticker(ticker),
        "symbol": ticker,
        "price": indicators.price if indicators.price is not None else quote.get("price"),
        "previous_close": quote.get("previous_close"),
        "change": quote.get("change"),
        "change_pct": quote.get("change_pct"),
        "currency": quote.get("currency"),
        "market_state": quote.get("market_state"),
        "market_time_jst": quote.get("market_time_jst"),
        "signal": StocksAgent._signal_label(indicators),
        "signal_score": indicators.signal_score,
        "trend": indicators.trend,
        "rsi14": indicators.rsi14,
        "macd": indicators.macd,
        "macd_signal": indicators.macd_signal,
        "sma20": indicators.sma20,
        "sma50": indicators.sma50,
        "volatility20": indicators.volatility20,
        "bollinger_mid20": indicators.bollinger_mid20,
        "bollinger_upper20": indicators.bollinger_upper20,
        "bollinger_lower20": indicators.bollinger_lower20,
        "data_source": "Yahoo Finance",
    }


@dashboard_bp.route("/stock-dashboard")
@requires_dashboard_access
def stock_dashboard():
    user_id = resolve_user_id(request.args.get("user_id"))
    error = _require_user_id(user_id)
    if error:
        return error
    return render_template("stock_dashboard.html", user_id=user_id)


@dashboard_bp.route("/api/stock-dashboard/analyze", methods=["POST"])
@requires_dashboard_access
def stock_dashboard_analyze():
    data = request.get_json(silent=True) or {}
    tickers = _normalize_stock_dashboard_tickers(data.get("tickers"))
    if not tickers:
        return jsonify({"ok": False, "error": "ticker is required"}), 400

    results = []
    errors = []
    for ticker in tickers:
        try:
            results.append(_analyze_stock_dashboard_ticker(ticker))
        except Exception:
            current_app.logger.exception("STOCK DASHBOARD ANALYSIS ERROR: %s", ticker)
            errors.append({"ticker": StocksAgent._display_ticker(ticker), "error": "market data unavailable"})

    results.sort(key=lambda item: (-item["signal_score"], item["ticker"]))
    return jsonify({
        "ok": True,
        "results": results,
        "errors": errors,
        "limits": {"max_tickers": _STOCK_DASHBOARD_MAX_TICKERS},
        "notice": "テクニカル指標による参考情報です。売買注文は実行しません。",
    })
