#!/usr/bin/env python3
"""Publish a read-only Orca snapshot to the dashboard receiver.

The local collector is intentionally separate: feed this script a JSON snapshot
built from the supported Orca CLI/API on the Mac. No Orca commands are guessed
or executed by this publisher.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_PAYLOAD_BYTES = 65536
MAX_ITEMS_PER_GROUP = 100
GROUPS = ("tasks", "dispatches", "workers")


def validate_snapshot(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be a JSON object")
    for group in GROUPS:
        items = payload.get(group, [])
        if not isinstance(items, list) or len(items) > MAX_ITEMS_PER_GROUP:
            raise ValueError(f"{group} must be an array of at most {MAX_ITEMS_PER_GROUP} objects")
        if any(not isinstance(item, dict) for item in items):
            raise ValueError(f"{group} entries must be objects")
    return payload


def publish_snapshot(endpoint: str, secret: str, payload: dict, timeout: float = 10.0) -> int:
    if not endpoint.startswith("https://"):
        raise ValueError("ORCA_STATUS_URL must use HTTPS")
    if not secret:
        raise ValueError("ORCA_STATUS_SECRET is required")
    snapshot = validate_snapshot(payload)
    raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"snapshot exceeds {MAX_PAYLOAD_BYTES} bytes")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    request = Request(
        endpoint.rstrip("/") + "/internal/orca/status",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Orca-Signature": signature,
            "User-Agent": "line-bot-orca-status-publisher/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        status = int(response.status)
        if status < 200 or status >= 300:
            raise RuntimeError(f"dashboard returned HTTP {status}")
        return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON snapshot file; default reads stdin")
    args = parser.parse_args(argv)
    endpoint = os.environ.get("ORCA_STATUS_URL", "").strip()
    secret = os.environ.get("ORCA_STATUS_SECRET", "")
    if not endpoint or not secret:
        parser.error("set ORCA_STATUS_URL and ORCA_STATUS_SECRET in the environment")
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1) if args.input == "-" else Path(args.input).read_bytes()
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"snapshot exceeds {MAX_PAYLOAD_BYTES} bytes")
        payload = json.loads(raw.decode("utf-8"))
        status = publish_snapshot(endpoint, secret, payload)
        print(f"Orca snapshot sent: HTTP {status}")
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, HTTPError, URLError, RuntimeError) as exc:
        print(f"Orca snapshot not sent: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
