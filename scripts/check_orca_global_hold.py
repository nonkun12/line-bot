"""Fail-closed preflight for the ORCA D1 Global HOLD control."""
from __future__ import annotations

import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen
from typing import Callable, Any


def read_global_hold(
    api_url: str,
    api_token: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, object]:
    if not isinstance(api_url, str) or not api_url.startswith(("https://", "http://")):
        raise RuntimeError("ORCA_TASK_API_URL is missing or invalid")
    if not isinstance(api_token, str) or not api_token.strip():
        raise RuntimeError("ORCA_TASK_API_TOKEN is missing")
    endpoint = api_url.rstrip("/") + "/control/global-hold"
    request = Request(
        endpoint,
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=10) as response:
            if getattr(response, "status", 200) != 200:
                raise RuntimeError("Global HOLD endpoint returned a non-200 response")
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Global HOLD state is unavailable; refusing to continue") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Global HOLD response is invalid")
    if payload.get("clear") is not True or payload.get("value") != "off" or payload.get("blocked") is not False:
        raise RuntimeError("Global HOLD is active or state is not explicitly clear")
    return payload


def main() -> int:
    try:
        read_global_hold(
            os.environ.get("ORCA_TASK_API_URL", ""),
            os.environ.get("ORCA_TASK_API_TOKEN", ""),
        )
    except Exception as exc:
        print(f"::error::ORCA Global HOLD blocked execution: {exc}", file=sys.stderr)
        return 1
    print("ORCA Global HOLD explicitly OFF; preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
