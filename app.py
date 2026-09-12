from flask import Flask, request, jsonify
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
import unicodedata
import json
import random
import threading
import httpx
import logging
logging.basicConfig(level=logging.DEBUG)
import re
import os
import time
from urllib.parse import urlencode
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

from config import (
    CHANNEL_ACCESS_TOKEN,
    CHANNEL_SECRET,
    GROQ_API_KEY,
    INTERNAL_PUSH_KEY,
    AI_REPORT_GITHUB_REPO,
    GITHUB_TOKEN,
    N8N_WEBHOOK_URL,
    configuration,
    handler,
    client,
    MODEL,
)
from db import (
    init_db,
    save_message,
    load_history,
    create_processed_event,
    is_processed_event,
)
from reminders import (
    handle_daily_reminder,
    handle_relative_time_reminder,
    handle_tomorrow_reminder,
)
from agents.notes.intents import is_note_intent
from agents.github.intents import is_github_intent
from mcp_client import (
    call_mcp_tool as _call_mcp_tool_impl,
    parse_mcp_json_list as _parse_mcp_json_list_impl,
)
from ai_client import (
    generate_chat_completion,
    generate_secretary_report,
    client as _ai_client_client,
)
from bot_tools import (
    MCP_TOOLS_SCHEMA as _MCP_TOOLS_SCHEMA,
    extract_quoted_text as _extract_quoted_text_impl,
    normalize_memory_key as _normalize_memory_key_impl,
    ensure_jst_offset as _ensure_jst_offset_impl,
    clean_memory_value as _clean_memory_value_impl,
    dispatch_tool_call as _dispatch_tool_call_impl,
)

from debug_agent import run_debug_agent
from internal_ask_route import register_internal_ask_route
from n8n_delegate import _delegate_to_n8n
from e2e_status import init_e2e_table, record_step, StepTimer
from core.channel import handle_channel_request
from core.gateway import AIGateway
from core.request_path import run_core_request, extract_core_reply
from routes.core_api import core_api_bp
from routes.voice_api import voice_api_bp
from line_development import extract_development_instruction, dispatch_development_workflow
from slack_command import register_slack_command

app = Flask(__name__)

from routes.dashboard import dashboard_bp
app.register_blueprint(dashboard_bp)

from routes.e2e_dashboard import e2e_bp
app.register_blueprint(e2e_bp)
app.register_blueprint(core_api_bp)
app.register_blueprint(voice_api_bp)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200

client = _ai_client_client
generate_ai_secretary_report = generate_secretary_report

LINE_MAX_MESSAGE_LENGTH = 5000
LINE_MAX_MESSAGES_PER_SEND = 5
LINE_MAX_TOTAL_LENGTH = LINE_MAX_MESSAGE_LENGTH * LINE_MAX_MESSAGES_PER_SEND
_LINE_TRUNCATION_NOTICE = "\n\n(※文字数が多いため一部を省略しました)"


def split_line_message(text, max_len=LINE_MAX_MESSAGE_LENGTH, max_messages=LINE_MAX_MESSAGES_PER_SEND, max_total=LINE_MAX_TOTAL_LENGTH):
    if not text:
        return [text or ""]
    truncated = False
    working = text
    if len(working) > max_total:
        working = working[:max_total]
        truncated = True
    if len(working) <= max_len:
        chunks = [working]
    else:
        chunks = []
        remaining = working
        while len(remaining) > max_len:
            window = remaining[:max_len]
            split_at = window.rfind("\n")
            if split_at <= 0:
                chunks.append(remaining[:max_len])
                remaining = remaining[max_len:]
            else:
                chunks.append(remaining[:split_at + 1])
                remaining = remaining[split_at + 1:]
        if remaining:
            chunks.append(remaining)
    if len(chunks) > max_messages:
        chunks = chunks[:max_messages]
        truncated = True
    if not chunks:
        chunks = [""]
    if truncated:
        notice = _LINE_TRUNCATION_NOTICE
        last = chunks[-1]
        available = max(0, max_len - len(notice))
        if len(last) > available:
            last = last[:available]
        chunks[-1] = last + notice
    return chunks


def _build_line_messages(text):
    return [TextMessage(text=chunk) for chunk in split_line_message(text)]


def _line_reply(reply_token, text):
    with StepTimer("line_out") as timer:
        try:
            with ApiClient(configuration) as api:
                MessagingApi(api).reply_message(
                    ReplyMessageRequest(reply_token=reply_token, messages=_build_line_messages(text))
                )
        except Exception as exc:
            timer.fail(error=exc, error_location="app._line_reply")
            raise
        timer.ok(http_status=200)


def _line_push(user_id, text):
    with StepTimer("line_out") as timer:
        try:
            with ApiClient(configuration) as api:
                MessagingApi(api).push_message(
                    PushMessageRequest(to=user_id, messages=_build_line_messages(text))
                )
        except Exception as exc:
            timer.fail(error=exc, error_location="app._line_push")
            raise
        timer.ok(http_status=200)

print("===== APP VERSION CHECK =====")
print("search_notes enabled")
init_db()
init_e2e_table()


def call_mcp_tool(tool_name, arguments, timeout=3.0):
    return _call_mcp_tool_impl(tool_name, arguments, timeout=timeout)


def _parse_mcp_json_list(raw):
    return _parse_mcp_json_list_impl(raw)

_DIRECT_TEXT_AGENT_KEYS = ("memory", "notes", "normal", "sheets")


def _invoke_graph(user_id: str, message: str):
    from graph.graph import graph
    return graph.invoke({
        "user_id": user_id,
        "raw_message": message,
        "call_mcp_tool": call_mcp_tool,
        "agent_results": {},
    })


def _extract_graph_reply(result):
    if result is None:
        return None
    agent_results = result.get("agent_results", {}) or {}
    for key in _DIRECT_TEXT_AGENT_KEYS:
        agent_result = agent_results.get(key)
        if isinstance(agent_result, dict) and "text" in agent_result:
            return agent_result["text"]
    return result.get("final_reply", "Agent結果なし")


def extract_quoted_text(original_message):
    return _extract_quoted_text_impl(original_message)


def normalize_memory_key(key, original_message):
    return _normalize_memory_key_impl(key, original_message)


def ensure_jst_offset(remind_at):
    return _ensure_jst_offset_impl(remind_at)

MCP_TOOLS_SCHEMA = _MCP_TOOLS_SCHEMA


def clean_memory_value(key, value):
    return _clean_memory_value_impl(key, value)


def dispatch_tool_call(user_id, name, arguments, original_message=""):
    return _dispatch_tool_call_impl(user_id, name, arguments, original_message=original_message)

_pending_delete_confirmation = {}
_pending_confirm_lock = threading.Lock()
_DELETE_ALL_MEMORY_PATTERN = re.compile(
    r"記憶.*(全部|全て|すべて).*(消して|消す|削除|消していい)"
    r"|(全部|全て|すべて).*記憶.*(消して|消す|削除|消していい)"
)


def generate_reply(user_id, message):
    print("===== APP VERSION CHECK =====")
    print("GITHUB ROUTE ENABLED")
    print("=== GENERATE_REPLY: received ===")
    print("MESSAGE DEBUG: received")

    if str(message).strip() == "ダッシュボード":
        ts = int(time.time())
        secret = os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""
        payload = f"{user_id}:{ts}"
        token = __import__("hmac").new(secret.encode(), payload.encode(), __import__("hashlib").sha256).hexdigest()
        query = urlencode({"user_id": user_id, "ts": ts, "token": token})
        dashboard_url = f"https://line-bot-yvea.onrender.com/dashboard?{query}"
        print("[LOG] generate_reply: dashboard command")
        print("[LOG] generate_reply: dashboard route ENABLED")
        return f"ダッシュボードはこちらです。\n{dashboard_url}"

    if "Daily AI Repo" in message:
        print("DAILY AI REPORT TRIGGERED")
        return generate_ai_secretary_report(user_id)

    if message.startswith("pytest"):
        return "pytestテストメッセージを受信しました。"

    print("DEBUG CONDITION CHECK")
    print("startswith debug:", message.startswith("debug"))
    print("has github:", "github" in message.lower())
    print("has search:", "search" in message.lower())
    print("has repo:", "repo" in message.lower())
    print("GITHUB INTENT RESULT:", is_github_intent(message))

    try:
        result = _invoke_graph(user_id, message)
    except Exception:
        print("===== GRAPH INVOCATION ERROR =====")
        print("graph invocation failed")
        return "AIサービスで一時的な問題が発生しました。少し時間を置いてもう一度お試しください。"

    print("===== AFTER GRAPH.INVOKE: completed =====")
    return _extract_graph_reply(result)


def _core_dynamic_enabled():
    return os.environ.get("AI_CORE_DYNAMIC_GRAPH", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _handle_ai_gateway_request(ai_request):
    message = str(ai_request.message)
    user_id = str(ai_request.user_id)

    development_instruction = extract_development_instruction(message)
    if development_instruction is not None:
        return dispatch_development_workflow(
            development_instruction,
            user_id=user_id,
            token=GITHUB_TOKEN,
            repository=AI_REPORT_GITHUB_REPO,
        )

    if not _core_dynamic_enabled():
        return generate_reply(user_id, message)

    if message.strip() == "ダッシュボード" or "Daily AI Repo" in message or message.startswith("pytest"):
        return generate_reply(user_id, message)

    result = run_core_request(
        user_id,
        message,
        channel=ai_request.channel,
        metadata=ai_request.metadata,
        call_mcp_tool=call_mcp_tool,
    )
    return extract_core_reply(result)


app.ai_gateway = AIGateway(_handle_ai_gateway_request)


def _gateway_reply(user_id, message):
    response = handle_channel_request(
        app.ai_gateway,
        str(user_id),
        str(message),
        "internal",
        metadata={"route": "internal_ask"},
    )
    return response.text


register_internal_ask_route(app, INTERNAL_PUSH_KEY, _gateway_reply)
register_slack_command(app)


@app.route("/callback", methods=["POST"])
def callback():
    print("[LOG] /callback endpoint called")
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature")
    print("===== CALLBACK RECEIVED =====")
    print("BODY LENGTH:", len(body))
    print("SIGNATURE PRESENT:", bool(signature))
    try:
        handler.handle(body, signature)
        return "OK", 200
    except Exception:
        print("===== HANDLER ERROR =====")
        print("handler failed")
        record_step(
            "line_in",
            False,
            error="handler_failed",
            error_location="callback/handler.handle",
        )
        return jsonify({"ok": False, "error": "internal server error"}), 500


_processed_message_ids = OrderedDict()
_processed_lock = threading.Lock()
_MAX_TRACKED_IDS = 2000
_user_processing_locks = {}
_user_processing_lock = threading.Lock()


def _process_and_reply(event, user_id, text):
    print("[LOG] _process_and_reply called")
    with _user_processing_lock:
        if user_id not in _user_processing_locks:
            _user_processing_locks[user_id] = threading.Lock()
    user_lock = _user_processing_locks[user_id]
    with user_lock:
        print("[LOG] USER LOCK ACQUIRED")
        if text.strip() == "ダッシュボード":
            ts = int(time.time())
            secret = os.environ.get("DASHBOARD_LINK_SECRET") or os.environ.get("DASHBOARD_PASSWORD") or ""
            payload = f"{user_id}:{ts}"
            token = __import__("hmac").new(secret.encode(), payload.encode(), __import__("hashlib").sha256).hexdigest()
            query = urlencode({"user_id": user_id, "ts": ts, "token": token})
            dashboard_url = f"https://line-bot-yvea.onrender.com/dashboard?{query}"
            _line_reply(event.reply_token, f"ダッシュボードはこちらです。\n{dashboard_url}")
            return
        try:
            ai_response = handle_channel_request(
                app.ai_gateway,
                str(user_id),
                str(text),
                "line",
                metadata={"route": "line_callback"},
            )
            reply = ai_response.text
        except Exception:
            print("[LOG] Core gateway failed; returning safe reply")
            reply = "AIサービスで一時的な問題が発生しました。少し時間を置いてもう一度お試しください。"
        try:
            _line_reply(event.reply_token, reply)
        except Exception:
            print("[LOG] LINE reply failed; falling back to push")
            _line_push(user_id, reply)
