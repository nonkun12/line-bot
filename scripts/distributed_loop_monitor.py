"""Read-only health monitor for the distributed autonomous loop.

This module never dispatches workflows, changes queue/recovery state, or grants
execution permission. Missing or malformed evidence is reported as BLOCKED.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def evaluate(runs_payload: Any, durable_payload: Any, *, run_id: str,
             head_sha: str, started_at: str) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []

    runs_ok = (
        isinstance(runs_payload, dict)
        and isinstance(runs_payload.get("workflow_runs"), list)
        and all(isinstance(item, dict) for item in runs_payload["workflow_runs"])
    )
    checks["actions_api"] = {
        "status": "PASS" if runs_ok else "BLOCKED",
        "detail": "Recent workflow runs retrieved" if runs_ok else "Actions evidence missing or malformed",
    }
    if not runs_ok:
        reasons.append("Actions API evidence unavailable")

    state_ok = isinstance(durable_payload, dict)
    recovery = durable_payload.get("recovery_ai") if state_ok else None
    recovery_ok = (
        isinstance(recovery, dict)
        and type(recovery.get("schema_version")) is int
        and recovery.get("schema_version") == 1
        and isinstance(recovery.get("tasks"), dict)
        and "checkpoint" in recovery
    )
    checks["durable_state"] = {
        "status": "PASS" if state_ok else "BLOCKED",
        "detail": "Durable loop state parsed" if state_ok else "Durable state missing or malformed",
    }
    checks["recovery_schema"] = {
        "status": "PASS" if recovery_ok else "BLOCKED",
        "detail": "Recovery AI schema validated" if recovery_ok else "Recovery AI schema invalid or missing",
    }
    if not state_ok or not recovery_ok:
        reasons.append("Durable Recovery AI evidence unavailable or invalid")

    held_ids: list[str] = []
    review_ids: list[str] = []
    if recovery_ok:
        for task_id, record in recovery["tasks"].items():
            if not isinstance(record, dict):
                reasons.append("Recovery task record malformed")
                continue
            if record.get("held") is True:
                held_ids.append(str(task_id))
            if record.get("resume_requires_review") is True:
                review_ids.append(str(task_id))
    if held_ids or review_ids:
        checks["recovery_safety"] = {
            "status": "BLOCKED",
            "held_task_count": len(held_ids),
            "resume_review_required_count": len(review_ids),
            "detail": "Held or review-pending tasks detected; no state was changed",
        }
        reasons.append("HOLD or pending resume review detected")
    elif recovery_ok:
        checks["recovery_safety"] = {
            "status": "PASS",
            "held_task_count": 0,
            "resume_review_required_count": 0,
            "detail": "No held or review-pending task flags detected",
        }
    else:
        checks["recovery_safety"] = {"status": "BLOCKED", "detail": "Cannot evaluate recovery safety"}

    if runs_ok:
        active = [
            item for item in runs_payload["workflow_runs"]
            if item.get("name") == "Distributed Autonomous Development Loop"
            and item.get("status") in {"queued", "in_progress"}
        ]
        checks["main_loop_activity"] = {
            "status": "PASS",
            "active_run_count": len(active),
            "detail": "Active Main LOOP runs observed; monitor did not dispatch or cancel anything",
        }

    status = "BLOCKED" if reasons else "PASS"
    return {
        "schema_version": 1,
        "run_id": str(run_id),
        "head_sha": head_sha if re.fullmatch(r"[0-9a-f]{40}", head_sha or "") else None,
        "scheduled_at": None,
        "schedule_expression": "*/30 * * * * (UTC)",
        "started_at": started_at,
        "completed_at": utc_now(),
        "status": status,
        "dispatch_allowed": False,
        "checks": checks,
        "failure_reason": "; ".join(dict.fromkeys(reasons)) or None,
        "limitations": [
            "Queue eligibility and independent human approval are not evaluated by this monitor.",
            "A PASS is health evidence only and never authorizes task execution.",
            "GitHub scheduled events may be delayed or skipped; this report does not imply a missed run succeeded.",
        ],
    }


def decode_github_contents(payload: Any) -> Any:
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        return None
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    try:
        return json.loads(base64.b64decode(content, validate=False).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-json", required=True)
    parser.add_argument("--state-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = utc_now()
    runs = load_json(args.runs_json)
    state_response = load_json(args.state_json)
    state = decode_github_contents(state_response)
    report = evaluate(
        runs, state,
        run_id=os.environ.get("GITHUB_RUN_ID", "unknown"),
        head_sha=os.environ.get("GITHUB_SHA", ""),
        started_at=started,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "dispatch_allowed": False,
                      "failure_reason": report["failure_reason"]}, ensure_ascii=False))
    return 0 if report["status"] in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
