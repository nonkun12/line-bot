#!/usr/bin/env python3
"""Outbound-only worker that forwards queued LINE tasks to local OpenClaw.

Required environment:
  OPENCLAW_BRIDGE_SERVER_URL=https://<your-render-host>/api/openclaw
  OPENCLAW_BRIDGE_KEY=<same secret configured on the server>
Optional:
  OPENCLAW_BIN=/path/to/openclaw
  OPENCLAW_AGENT_ID=main
  OPENCLAW_AGENT_TIMEOUT_SECONDS=300
Run once by default; pass --watch for bounded continuous polling.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

import httpx

POLL_SECONDS = 5
HTTP_TIMEOUT_SECONDS = 15
MAX_MESSAGE_CHARS = 4000
MAX_REPLY_CHARS = 12000


def validate_config(server_url: str, key: str) -> str:
    parsed = urlparse(server_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("server URL must use HTTPS (HTTP is allowed only for loopback)")
    if not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("invalid bridge server URL")
    if not key or len(key) < 24:
        raise ValueError("bridge key must be configured and at least 24 characters")
    return server_url.rstrip("/")


def run_openclaw(message: str, timeout_seconds: int) -> str:
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_CHARS:
        raise ValueError("invalid queued message")
    binary = os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw")
    if not binary:
        raise RuntimeError("openclaw CLI was not found")
    # Argument array only: never pass the task through a shell.
    completed = subprocess.run(
        [binary, "agent", "--agent", os.environ.get("OPENCLAW_AGENT_ID", "main"), "--message", message.strip()],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        # Do not forward local stderr; it may contain paths or configuration details.
        raise RuntimeError("openclaw agent exited unsuccessfully")
    output = (completed.stdout or "").strip()
    if not output:
        raise RuntimeError("openclaw agent returned an empty response")
    return output[:MAX_REPLY_CHARS]


def process_one(client: httpx.Client, base_url: str, headers: dict[str, str], timeout: int) -> bool:
    response = client.post(f"{base_url}/claim", headers=headers, json={})
    response.raise_for_status()
    payload = response.json()
    job = payload.get("job")
    if not isinstance(job, dict):
        return False
    job_id, token, message = job.get("id"), job.get("claim_token"), job.get("message")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise RuntimeError("server returned an invalid job id")
    if not isinstance(token, str) or not token or not isinstance(message, str):
        raise RuntimeError("server returned an invalid job payload")
    try:
        reply = run_openclaw(message, timeout)
        result = {"job_id": job_id, "claim_token": token, "success": True, "reply": reply}
    except subprocess.TimeoutExpired:
        result = {"job_id": job_id, "claim_token": token, "success": False,
                  "error": "OpenClaw execution timed out"}
    except Exception as exc:
        # Send only a stable category; never expose exception details or local output.
        category = "timeout" if "timeout" in type(exc).__name__.lower() else "execution_error"
        result = {"job_id": job_id, "claim_token": token, "success": False,
                  "error": f"OpenClaw {category}"}
    done = client.post(f"{base_url}/complete", headers=headers, json=result)
    done.raise_for_status()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="poll continuously; default is one job/check")
    args = parser.parse_args()
    try:
        base_url = validate_config(
            os.environ.get("OPENCLAW_BRIDGE_SERVER_URL", ""),
            os.environ.get("OPENCLAW_BRIDGE_KEY", ""),
        )
        timeout = int(os.environ.get("OPENCLAW_AGENT_TIMEOUT_SECONDS", "300"))
        if timeout < 10 or timeout > 900:
            raise ValueError("OPENCLAW_AGENT_TIMEOUT_SECONDS must be between 10 and 900")
    except (ValueError, TypeError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    headers = {"X-OpenClaw-Bridge-Key": os.environ["OPENCLAW_BRIDGE_KEY"]}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            while True:
                try:
                    worked = process_one(client, base_url, headers, timeout)
                except Exception as exc:
                    print(f"bridge request failed: {type(exc).__name__}", file=sys.stderr)
                    if not args.watch:
                        return 1
                    time.sleep(POLL_SECONDS)
                    continue
                if not args.watch:
                    return 0
                if not worked:
                    time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
