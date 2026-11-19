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
    "tasks": {"id", "task_id", "status", "state", "stage", "created_at", "updated_at", "dispatch_id", "worker_id", "stream_key", "rea_artifact_status", "rea_artifact_reason_code", "rea_artifact_evidence_sha256", "rea_artifact_execution_authorized", "rea_artifact_patch_authorized", "rea_artifact_hold_clear_authorized", "rea_artifact_merge_deploy_authorized"},
    "dispatches": {"id", "dispatch_id", "task_id", "status", "state", "stage", "created_at", "updated_at", "worker_id", "stream_key"},
    "workers": {"id", "worker_id", "dispatch_id", "task_id", "status", "state", "stage", "addressable", "exactWorker", "created_at", "updated_at", "stream_key"},
}
STREAM_KEYS = {"main_star_night", "side_task_supply", "side_media_ai", "side_self_improvement", "side_line_full_control", "side_core_vocabulary"}


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
        if group == "tasks":
            for source, target in zip(items, clean[group]):
                if any(key in source for key in ("rea_artifact_status", "rea_artifact_reason_code", "rea_artifact_evidence_sha256")):
                    if source.get("rea_artifact_status") not in {"PASS", "FAIL", "NO_CHANGE", "BLOCKED", "HOLD"}:
                        raise ValueError("invalid REA artifact status")
                    digest = source.get("rea_artifact_evidence_sha256")
                    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                        raise ValueError("invalid REA artifact evidence hash")
                    flags = ("rea_artifact_execution_authorized", "rea_artifact_patch_authorized", "rea_artifact_hold_clear_authorized", "rea_artifact_merge_deploy_authorized")
                    if any(source.get(flag) is not False for flag in flags):
                        raise ValueError("REA artifact authority flags must remain false")
    streams = payload.get("streams", [])
    if not isinstance(streams, list) or len(streams) > 6:
        raise ValueError("streams must be an array of at most six objects")
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
    work_finder = payload.get("work_finder")
    if work_finder is not None:
        if not isinstance(work_finder, dict):
            raise ValueError("work_finder must be an object")
        if work_finder.get("cycle_status") not in {"WORK_FOUND", "NO_SAFE_CANDIDATE", "BLOCKED"}:
            raise ValueError("invalid Work Finder cycle status")
        if work_finder.get("execution_eligibility_status") not in {"verified", "not_proven"}:
            raise ValueError("invalid execution eligibility status")
        if work_finder.get("candidate_policy") != "review_only_no_execution_approval":
            raise ValueError("Work Finder candidates must remain review-only")
        safety = work_finder.get("safety")
        if not isinstance(safety, dict) or safety.get("read_only") is not True or safety.get("execution_approval_granted") is not False:
            raise ValueError("Work Finder safety contract must remain read-only")
        allowed_counts = {"discovered_candidate_count", "review_pending_count", "completed_task_count",
                          "catalog_task_count", "runtime_queue_task_count", "held_task_count",
                          "resume_review_required_count", "scanned_target_pairs", "execution_eligible_count"}
        clean_counts = {}
        for key in allowed_counts:
            value = work_finder.get(key)
            if value is None and key == "execution_eligible_count":
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10000:
                raise ValueError(f"invalid Work Finder count: {key}")
            clean_counts[key] = value
        next_actions = {"human_review_candidates", "review_catalog_runtime_plan_gaps",
                        "expand_allowlisted_discovery_sources", "investigate_discovery_status"}
        if work_finder.get("next_action") not in next_actions:
            raise ValueError("invalid Work Finder next action")
        previews = work_finder.get("candidate_preview", [])
        if not isinstance(previews, list) or len(previews) > 5:
            raise ValueError("invalid Work Finder candidate preview list")
        clean_previews = []
        for item in previews:
            if not isinstance(item, dict) or item.get("status") != "REVIEW_REQUIRED":
                raise ValueError("invalid Work Finder candidate preview")
            clean_item = {}
            for key, limit in (("id", 100), ("target_test", 200), ("source_function", 120), ("evidence", 250)):
                value = item.get(key)
                if not isinstance(value, str) or not value.strip() or len(value) > limit:
                    raise ValueError(f"invalid Work Finder candidate field: {key}")
                clean_item[key] = value.strip()
            clean_item["status"] = "REVIEW_REQUIRED"
            clean_previews.append(clean_item)
        clean["work_finder"] = {
            "cycle_status": work_finder["cycle_status"],
            "next_action": work_finder["next_action"],
            "execution_eligibility_status": work_finder["execution_eligibility_status"],
            "candidate_policy": work_finder["candidate_policy"],
            "candidate_preview": clean_previews,
            "safety": {"read_only": True, "execution_approval_granted": False},
            **clean_counts,
        }
    review = payload.get("rsi_review")
    if review is not None:
        if not isinstance(review, dict):
            raise ValueError("rsi_review must be an object")
        if review.get("status") not in {"PASS", "FAIL", "BLOCKED", "NO_CHANGE"}:
            raise ValueError("invalid RSI review status")
        flags = ("allow_continue", "execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized", "scheduler_started", "model_activated")
        if any(review.get(flag) is not False for flag in flags) or review.get("proposal_only") is not True:
            raise ValueError("RSI review must remain proposal-only with all authority flags false")
        count = review.get("review_count")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 20:
            raise ValueError("invalid RSI review count")
        event_ids = review.get("review_evidence_event_ids", [])
        if not isinstance(event_ids, list) or len(event_ids) > 20 or any(not isinstance(x, str) or not x.startswith("orchestra-rea:") or len(x) > 180 for x in event_ids):
            raise ValueError("invalid RSI review evidence references")
        allowed = {"phase", "status", "reason_code", "next_action", "repository", "head_sha", "review_count", "review_evidence_event_ids", "allow_continue", "proposal_only", "execution_authorized", "patch_authorized", "hold_clear_authorized", "merge_deploy_authorized", "scheduler_started", "model_activated"}
        clean["rsi_review"] = {k: v for k, v in review.items() if k in allowed and ((isinstance(v, (str, int, bool)) and len(str(v)) <= 300) or (k == "review_evidence_event_ids" and isinstance(v, list)))}
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
