import json
import os
import re
import time
import uuid
import math
import threading
from urllib.parse import urlsplit

import httpx

from config import MCP_SERVER_URL, MCP_API_KEY


_HIBERNATE_STATE_LOCK = threading.Lock()
_HIBERNATE_COOLDOWN_UNTIL = 0.0
_HIBERNATE_WAKE_OWNER = False

def _finite_env_float(name, default, *, minimum, maximum):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    return min(max(value, minimum), maximum)

def _hibernate_retry_settings():
    """Return finite, bounded retry settings for Render Free hibernation responses."""
    max_wait = _finite_env_float(
        "MCP_HIBERNATE_RETRY_MAX_SEC", 120.0, minimum=0.0, maximum=300.0
    )
    interval = _finite_env_float(
        "MCP_HIBERNATE_RETRY_INTERVAL_SEC", 60.0, minimum=1.0, maximum=120.0
    )
    return max_wait, interval

def _claim_hibernate_wake():
    """Allow only one process-wide hibernate wake/retry sequence at a time."""
    global _HIBERNATE_COOLDOWN_UNTIL, _HIBERNATE_WAKE_OWNER
    now = time.monotonic()
    with _HIBERNATE_STATE_LOCK:
        if now < _HIBERNATE_COOLDOWN_UNTIL or _HIBERNATE_WAKE_OWNER:
            return False
        _HIBERNATE_WAKE_OWNER = True
        return True

def _release_hibernate_wake(cooldown_sec):
    global _HIBERNATE_COOLDOWN_UNTIL, _HIBERNATE_WAKE_OWNER
    with _HIBERNATE_STATE_LOCK:
        _HIBERNATE_WAKE_OWNER = False
        _HIBERNATE_COOLDOWN_UNTIL = time.monotonic() + max(0.0, cooldown_sec)

def _hibernate_cooldown_active():
    with _HIBERNATE_STATE_LOCK:
        return time.monotonic() < _HIBERNATE_COOLDOWN_UNTIL or _HIBERNATE_WAKE_OWNER


def _is_hibernate_rate_limited(response):
    """Retry only Render's explicit hibernate-rate-limited 429 response."""
    if response.status_code != 429:
        return False
    routing = response.headers.get("x-render-routing", "").strip().lower()
    return routing == "hibernate-rate-limited"


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return float(default)


def mcp_health_url():
    """Return the unauthenticated HTTP health URL for the MCP service."""
    override = os.getenv("MCP_HEALTH_URL", "").strip()
    if override:
        return override
    parts = urlsplit(MCP_SERVER_URL)
    return f"{parts.scheme}://{parts.netloc}/health"


def _mcp_ready_check_enabled():
    return os.getenv("MCP_HTTP_READY_CHECK", "true").strip().lower() != "false"


class McpNotReadyError(RuntimeError):
    """MCP /health did not become ready in the bounded wait."""


def wait_for_mcp_http_ready(max_wait=None, poll_interval=None, stable_count=None):
    """
    Wait for stable HTTP readiness before issuing a write.

    Free Render hibernation can remain rate-limited beyond the platform's
    approximate one-minute wake-up time. Keep the wait bounded, but use
    exponential backoff so repeated health probes do not create a request
    storm while the service is waking.
    """
    if not _mcp_ready_check_enabled():
        return
    max_wait = _finite_env_float("MCP_READY_MAX_SEC", 180.0, minimum=0.0, maximum=300.0) if max_wait is None else max_wait
    poll_interval = _finite_env_float("MCP_READY_POLL_SEC", 5.0, minimum=0.1, maximum=30.0) if poll_interval is None else poll_interval
    stable_count = int(_finite_env_float("MCP_READY_STABLE_COUNT", 2, minimum=1, maximum=5)) if stable_count is None else stable_count
    max_wait = min(max(max_wait, 0.0), 300.0)
    poll_interval = min(max(poll_interval, 0.1), 30.0)
    stable_count = max(1, stable_count)
    deadline = time.monotonic() + max_wait
    consecutive = 0
    last_reason = "no response"
    current_interval = poll_interval
    while True:
        try:
            res = httpx.get(
                mcp_health_url(),
                timeout=httpx.Timeout(8.0, connect=8.0),
                follow_redirects=False,
            )
            ok = False
            if res.status_code == 200:
                try:
                    body = res.json()
                    ok = isinstance(body, dict) and body.get("ok") is True
                except ValueError:
                    ok = False
            last_reason = f"status={res.status_code} routing={res.headers.get('x-render-routing', '')}"
            res.close()
        except httpx.HTTPError as exc:
            ok = False
            last_reason = type(exc).__name__
        if ok:
            consecutive += 1
            if consecutive >= stable_count:
                print("MCP HTTP READY", flush=True)
                return
        else:
            consecutive = 0

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise McpNotReadyError(f"MCP server not ready ({last_reason})")

        sleep_for = min(current_interval, remaining)
        time.sleep(sleep_for)
        current_interval = min(current_interval * 2.0, 30.0)


def classify_mcp_failure(exc):
    """Classify MCP failures by delivery certainty; writes retry only when safe."""
    if isinstance(exc, (McpNotReadyError, httpx.ConnectError, httpx.ConnectTimeout)):
        return "not_delivered"
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        if _is_hibernate_rate_limited(response):
            return "not_delivered"
        if 400 <= response.status_code < 500:
            return "rejected"
    return "ambiguous"


def _call_mcp_tool_once(tool_name, arguments, timeout=None):
    """
    my-mcp-server の /mcp エンドポイントへ JSON-RPC で tools/call を送る。
    StreamableHTTPServerTransport はレスポンスを
    application/json または text/event-stream のどちらでも返し得るため両方に対応する。

    MCP_TIMEOUT_SEC が設定されていればそれを使用し、未設定時は10秒。
    Render Free等のcold startで3秒を超えるケースを考慮する。

    Render Free が自動スピンダウンから復帰する際に返す
    429 + x-render-routing=hibernate-rate-limited だけは、
    約1分の間隔で限定的に再試行し、最大120秒で打ち切る。
    それ以外の429/通信失敗は従来どおり即時失敗。
    """
    print(f"[LOG] call_mcp_tool called: tool_name={tool_name}")

    print("MCP CALL:", tool_name, arguments)
    print("MCP URL:", MCP_SERVER_URL)

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-api-key": MCP_API_KEY,
        "Connection": "close"
    }

    request_timeout = timeout
    if request_timeout is None:
        try:
            request_timeout = float(os.getenv("MCP_TIMEOUT_SEC", "10"))
        except ValueError:
            request_timeout = 10.0

    retry_max_wait, retry_interval = _hibernate_retry_settings()
    retry_deadline = time.monotonic() + retry_max_wait
    wake_owner = False
    wake_cooldown = 0.0
    if _hibernate_cooldown_active():
        raise McpNotReadyError("MCP hibernate cooldown is active")

    print("BEFORE MCP REQUEST")
    print("TIMEOUT:", request_timeout)
    print("POST START TIME:", time.time())
    try:
        while True:
            print("REQUEST START")
            print("MCP BEFORE REQUESTS POST")
            print("BEFORE POST CALL", time.time())
            res = httpx.post(
                MCP_SERVER_URL,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(request_timeout, connect=10.0),
                follow_redirects=False,
            )
            print("MCP AFTER REQUESTS POST")
            print("MCP RESPONSE STATUS:", res.status_code)
            print("MCP CONTENT TYPE:", res.headers.get("content-type"))
            print("RESPONSE OBJECT:", res)

            if not _is_hibernate_rate_limited(res):
                wake_cooldown = 0.0
                break

            if not wake_owner:
                if not _claim_hibernate_wake():
                    res.close()
                    raise McpNotReadyError("MCP hibernate wake already in progress")
                wake_owner = True
                wake_cooldown = retry_interval

            remaining = retry_deadline - time.monotonic()
            if remaining < retry_interval:
                print("MCP HIBERNATE RETRY DEADLINE EXCEEDED", flush=True)
                res.close()
                raise McpNotReadyError("MCP hibernate retry deadline exceeded")

            print(
                f"MCP HIBERNATE RATE LIMIT: retrying in "
                f"{retry_interval:.1f}s",
                flush=True,
            )
            res.close()
            time.sleep(retry_interval)
    except Exception as e:
        import traceback
        print("EXCEPTION TYPE:", type(e))
        traceback.print_exc()
        raise
    finally:
        if wake_owner:
            _release_hibernate_wake(wake_cooldown)
    print("REQUEST END")
    print("AFTER MCP REQUEST")
    print("POST END TIME:", time.time())

    print("MCP STATUS:", res.status_code)
    print("MCP HEADERS:", res.headers)

    res.raise_for_status()

    content_type = res.headers.get("content-type", "")

    if "text/event-stream" in content_type:
        body = None
        try:
            for line in res.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8")
                    if decoded_line.startswith("data:"):
                        data_line = decoded_line[len("data:"):].strip()
                        body = json.loads(data_line)
                        break
        finally:
            res.close()

        if body is None:
            raise RuntimeError("MCP SSEレスポンスにdataが見つかりません")
    else:
        try:
            body = res.json()
        finally:
            res.close()

    print("MCP PARSED BODY:", body)

    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")

    result = body.get("result", {})
    parts = result.get("content", [])
    texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
    return "\n".join(texts) if texts else ""


def call_mcp_tool(tool_name, arguments, timeout=None):
    """Call MCP, optionally wrapped in the dedicated on-demand Render session."""
    from render_client import mcp_service_session

    with mcp_service_session():
        return _call_mcp_tool_once(tool_name, arguments, timeout=timeout)


def _parse_reminder_text_lines(raw):
    """MCPの旧プレーンテキスト形式のreminder一覧を構造化する。"""
    items = []
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(
            r"id\s*[=:]\s*(\d+)\s*:\s*(.+?)\s+に「(.*?)」\s*(?:\(毎日繰り返し\))?$",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue

        reminder_id, remind_at, message = match.groups()
        items.append({
            "id": int(reminder_id),
            "remind_at": remind_at.strip(),
            "message": message,
            "repeat": "daily" if "(毎日繰り返し)" in line else "none",
        })
    return items


def parse_mcp_json_list(raw):
    print(f"[LOG] _parse_mcp_json_list called")

    if not raw:
        return []

    if isinstance(raw, list):
        return raw

    # list_reminders may return its legacy plain-text format directly.
    # Parse that before attempting JSON so expected responses do not emit
    # misleading JSON parse-error logs.
    reminder_items = _parse_reminder_text_lines(raw)
    if reminder_items:
        return reminder_items

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            content = (
                data.get("result", {})
                .get("content", [])
            )

            if content and isinstance(content[0], dict):
                text = content[0].get("text", "")

                parsed = None
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None

                if isinstance(parsed, list):
                    return parsed

                reminder_items = _parse_reminder_text_lines(text)
                if reminder_items:
                    return reminder_items
                return []

        return data if isinstance(data, list) else []

    except json.JSONDecodeError:
        # MCP tools may legitimately return human-readable text (for example
        # "予定されているリマインダーはありません"). Do not treat that as
        # a JSON parsing failure or surface a noisy error in Render logs.
        return []
