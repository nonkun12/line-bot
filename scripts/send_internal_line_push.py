"""Send one explicit LINE push through the application's authenticated endpoint."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PUSH_URL = "https://line-bot-yvea.onrender.com/internal/push"


@dataclass(frozen=True)
class PushResult:
    ok: bool
    http_status: int | None
    reason: str = ""


def send_internal_line_push(
    message: str,
    *,
    environ: Mapping[str, str] | None = None,
    opener: Callable = urlopen,
) -> PushResult:
    env = os.environ if environ is None else environ
    key = env.get("INTERNAL_PUSH_KEY", "").strip()
    user_id = env.get("DISTRIBUTED_LOOP_LINE_USER_ID", "").strip()
    if not key or not user_id:
        return PushResult(False, None, "missing_required_secrets:INTERNAL_PUSH_KEY,DISTRIBUTED_LOOP_LINE_USER_ID")
    if not message.strip():
        return PushResult(False, None, "empty_message")

    request = Request(
        PUSH_URL,
        data=json.dumps({"user_id": user_id, "message": message}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-internal-key": key},
        method="POST",
    )
    try:
        with opener(request, timeout=30) as response:
            status = int(response.status)
            body = response.read()
    except HTTPError as exc:
        status = int(exc.code)
        body = exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        return PushResult(False, None, f"transport_error:{type(exc).__name__}")
    except Exception as exc:
        return PushResult(False, None, f"request_error:{type(exc).__name__}")

    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return PushResult(False, status, "invalid_json_response")
    if not 200 <= status < 300:
        error = result.get("error") if isinstance(result, dict) else None
        allowed_errors = {
            "unauthorized": "unauthorized",
            "user_id and message are required": "invalid_payload",
            "internal server error": "internal_server_error",
            "line channel access token rejected": "line_channel_access_token_rejected",
        }
        safe_error = allowed_errors.get(str(error), "request_rejected")
        return PushResult(False, status, safe_error)
    if not isinstance(result, dict) or result.get("ok") is not True:
        return PushResult(False, status, "response_ok_false")
    return PushResult(True, status)


def main() -> int:
    if len(sys.argv) != 2:
        print("LINE_NOTIFICATION=FAILED")
        print("LINE_NOTIFICATION_ERROR=usage: send_internal_line_push.py MESSAGE_FILE")
        return 2
    try:
        message = Path(sys.argv[1]).read_text(encoding="utf-8")
    except OSError as exc:
        result = PushResult(False, None, f"message_file_error:{type(exc).__name__}")
    else:
        result = send_internal_line_push(message)

    print(f"LINE_NOTIFICATION={'SUCCESS' if result.ok else 'FAILED'}")
    print(f"LINE_NOTIFICATION_HTTP={result.http_status if result.http_status is not None else 'NOT_SENT'}")
    if result.reason:
        print(f"LINE_NOTIFICATION_ERROR={result.reason}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
