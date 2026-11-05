#!/usr/bin/env python3
"""Publish a bounded, allowlisted Orca snapshot over authenticated HTTPS."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_PAYLOAD_BYTES = 65536
MAX_ITEMS_PER_GROUP = 100
GROUPS = ("tasks", "dispatches", "workers")
ALLOWED_FIELDS = {
    "tasks": {"id", "task_id", "status", "state", "stage", "created_at", "updated_at", "dispatch_id", "worker_id", "stream_key"},
    "dispatches": {"id", "dispatch_id", "task_id", "status", "state", "stage", "created_at", "updated_at", "worker_id", "stream_key"},
    "workers": {"id", "worker_id", "dispatch_id", "task_id", "status", "state", "stage", "addressable", "exactWorker", "created_at", "updated_at", "stream_key"},
}
STREAM_KEYS = {"main_star_night", "side_task_supply", "side_media_ai", "side_self_improvement", "side_line_full_control"}


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("captured_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_snapshot(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be a JSON object")
    captured = _timestamp(payload.get("captured_at"))
    now = datetime.now(timezone.utc)
    age = (now - captured).total_seconds()
    if age < -60:
        raise ValueError("snapshot timestamp is in the future")
    if age > 300:
        raise ValueError("snapshot is older than 300 seconds")
    clean = {"captured_at": captured.isoformat(), "run_id": str(payload.get("run_id") or "")[:100]}
    for group in GROUPS:
        items = payload.get(group, [])
        if not isinstance(items, list) or len(items) > MAX_ITEMS_PER_GROUP:
            raise ValueError(f"{group} must be an array of at most {MAX_ITEMS_PER_GROUP} objects")
        if any(not isinstance(item, dict) for item in items):
            raise ValueError(f"{group} entries must be objects")
        clean[group] = [
            {k: v for k, v in item.items() if k in ALLOWED_FIELDS[group]
             and isinstance(v, (str, int, float, bool)) and len(str(v)) <= 300}
            for item in items
        ]
    streams = payload.get("streams", [])
    if not isinstance(streams, list) or len(streams) > 5:
        raise ValueError("streams must be an array of at most five objects")
    clean["streams"] = []
    for item in streams:
        if not isinstance(item, dict) or item.get("key") not in STREAM_KEYS:
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
    return clean


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
    request = Request(endpoint.rstrip("/") + "/internal/orca/status", data=raw,
                      headers={"Content-Type": "application/json", "X-Orca-Signature": signature,
                               "User-Agent": "line-bot-orca-status-publisher/1.0"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        status = int(response.status)
        if status < 200 or status >= 300:
            raise RuntimeError(f"dashboard returned HTTP {status}")
        return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-")
    args = parser.parse_args(argv)
    endpoint = os.environ.get("ORCA_STATUS_URL", "").strip()
    secret = os.environ.get("ORCA_STATUS_SECRET", "")
    if not endpoint or not secret:
        parser.error("set ORCA_STATUS_URL and ORCA_STATUS_SECRET")
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1) if args.input == "-" else Path(args.input).read_bytes()
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"snapshot exceeds {MAX_PAYLOAD_BYTES} bytes")
        status = publish_snapshot(endpoint, secret, json.loads(raw.decode("utf-8")))
        print(f"Orca snapshot sent: HTTP {status}")
        return 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, HTTPError, URLError, RuntimeError) as exc:
        print(f"Orca snapshot not sent: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
