"""Read-only health monitor for the distributed autonomous loop.

This module never dispatches workflows, changes queue/recovery state, or grants
execution permission. Missing, stale, or unverifiable evidence is BLOCKED.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Conservative ceiling: an older durable snapshot cannot support a healthy PASS.
# This is a monitoring safety bound, not a claim about the normal writer cadence.
MAX_STATE_AGE_HOURS = 24
MAX_FUTURE_CLOCK_SKEW_SECONDS = 300
SHA_RE = re.compile(r"[0-9a-f]{40}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def load_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def github_blob_sha(contents_response: Any) -> str | None:
    if not isinstance(contents_response, dict) or contents_response.get("encoding") != "base64":
        return None
    content = contents_response.get("content")
    if not isinstance(content, str):
        return None
    try:
        raw = base64.b64decode(content, validate=False)
    except (ValueError, TypeError):
        return None
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


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


def normalize_actions_runs(payload: Any) -> dict[str, Any] | None:
    """Normalize either a single Actions response or gh --paginate --slurp pages."""
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, list) or not payload:
        return None
    combined: list[Any] = []
    for page in payload:
        if not isinstance(page, dict) or not isinstance(page.get("workflow_runs"), list):
            return None
        combined.extend(page["workflow_runs"])
    return {"workflow_runs": combined}



MAIN_LOOP_WORKFLOW_ID = 357086091
MAX_QUEUED_SCHEDULE_AGE_SECONDS = 40 * 60
MAX_IN_PROGRESS_AGE_SECONDS = 50 * 60
VALID_RUN_STATUSES = {"queued", "in_progress", "completed"}
FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}


def evaluate_main_loop_runs(workflow_runs: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Classify Main LOOP run evidence without granting task-execution permission."""
    target = [item for item in workflow_runs if item.get("workflow_id") == MAIN_LOOP_WORKFLOW_ID]
    if not target:
        return {
            "status": "INFO", "outcome": "NO_CHANGE", "active_run_count": 0,
            "latest_run_id": None, "latest_run_attempt": None, "latest_conclusion": None,
            "detail": "No Main LOOP run found in the retrieved Actions window",
        }

    errors: list[str] = []
    normalized: dict[int, dict[str, Any]] = {}
    seen_attempts: dict[tuple[int, int], tuple[Any, ...]] = {}
    for item in target:
        run_id = item.get("id")
        attempt = item.get("run_attempt")
        created = parse_utc(item.get("created_at"))
        status = item.get("status")
        if type(run_id) is not int or run_id <= 0:
            errors.append("Main LOOP run has missing or invalid run id")
            continue
        if type(attempt) is not int or attempt <= 0:
            errors.append(f"Main LOOP run {run_id} has missing or invalid run_attempt")
            continue
        if created is None:
            errors.append(f"Main LOOP run {run_id} has missing or invalid created_at")
            continue
        if (created - now).total_seconds() > MAX_FUTURE_CLOCK_SKEW_SECONDS:
            errors.append(f"Main LOOP run {run_id} created_at is too far in the future")
            continue
        run_started = None
        if status == "in_progress":
            run_started = parse_utc(item.get("run_started_at"))
            if run_started is None:
                errors.append(f"Main LOOP run {run_id} has missing or invalid run_started_at")
                continue
            if (run_started - now).total_seconds() > MAX_FUTURE_CLOCK_SKEW_SECONDS:
                errors.append(f"Main LOOP run {run_id} run_started_at is too far in the future")
                continue
            if (created - run_started).total_seconds() > MAX_FUTURE_CLOCK_SKEW_SECONDS:
                errors.append(
                    f"Main LOOP run {run_id} run_started_at is earlier than created_at beyond clock-skew tolerance"
                )
                continue
        if not isinstance(item.get("event"), str) or not item["event"].strip():
            errors.append(f"Main LOOP run {run_id} has missing or invalid event")
            continue
        if status not in VALID_RUN_STATUSES:
            errors.append(f"Main LOOP run {run_id} has unknown status")
            continue
        run_number = item.get("run_number")
        if type(run_number) is not int or run_number <= 0:
            errors.append(f"Main LOOP run {run_id} has missing or invalid run_number")
            continue
        identity_fields = (
            "workflow_id", "run_number", "event", "status", "conclusion",
            "created_at", "run_started_at", "updated_at",
        )
        attempt_key = (run_id, attempt)
        identity = tuple(item.get(field) for field in identity_fields)
        seen_identity = seen_attempts.get(attempt_key)
        if seen_identity is not None and identity != seen_identity:
            errors.append(f"Main LOOP run {run_id} has conflicting records for the same attempt")
            continue
        seen_attempts[attempt_key] = identity

        previous = normalized.get(run_id)
        if previous is None or attempt > previous["run_attempt"]:
            normalized[run_id] = {**item, "_parsed_run_started_at": run_started}

    if errors:
        return {
            "status": "BLOCKED", "outcome": "UNVERIFIED", "active_run_count": None,
            "latest_run_id": None, "latest_run_attempt": None, "latest_conclusion": None,
            "detail": "; ".join(errors),
        }
    if not normalized:
        return {
            "status": "BLOCKED", "outcome": "UNVERIFIED", "active_run_count": None,
            "latest_run_id": None, "latest_run_attempt": None, "latest_conclusion": None,
            "detail": "Main LOOP run records could not be normalized",
        }

    runs = list(normalized.values())
    runs.sort(key=lambda item: (
        parse_utc(item["created_at"]),
        int(item.get("run_number") or 0),
        int(item["id"]),
        int(item["run_attempt"]),
    ))
    latest = runs[-1]
    active = [item for item in runs if item["status"] in {"queued", "in_progress"}]
    if len(active) > 1:
        return {
            "status": "BLOCKED", "outcome": "OVERLAP", "active_run_count": len(active),
            "latest_run_id": latest["id"], "latest_run_attempt": latest["run_attempt"],
            "latest_conclusion": latest.get("conclusion"),
            "detail": "Multiple Main LOOP runs are queued or in progress; overlap/backlog detected",
        }

    stale_queued = [
        item for item in active
        if item["status"] == "queued"
        and item.get("event") == "schedule"
        and int((now - parse_utc(item["created_at"])).total_seconds()) > MAX_QUEUED_SCHEDULE_AGE_SECONDS
    ]
    if stale_queued:
        stale = stale_queued[0]
        age_seconds = int((now - parse_utc(stale["created_at"])).total_seconds())
        return {
            "status": "BLOCKED", "outcome": "STALE_QUEUED", "active_run_count": len(active),
            "latest_run_id": latest["id"], "latest_run_attempt": latest["run_attempt"],
            "latest_conclusion": latest.get("conclusion"),
            "detail": f"Scheduled Main LOOP run {stale['id']} has waited {age_seconds}s; stale queue threshold is {MAX_QUEUED_SCHEDULE_AGE_SECONDS}s",
        }
    stale_running = [
        item for item in active
        if item["status"] == "in_progress"
        and int((now - item["_parsed_run_started_at"]).total_seconds()) > MAX_IN_PROGRESS_AGE_SECONDS
    ]
    if stale_running:
        stale = stale_running[0]
        age_seconds = int((now - stale["_parsed_run_started_at"]).total_seconds())
        return {
            "status": "BLOCKED", "outcome": "STALE_IN_PROGRESS", "active_run_count": len(active),
            "latest_run_id": latest["id"], "latest_run_attempt": latest["run_attempt"],
            "latest_conclusion": latest.get("conclusion"),
            "detail": f"Main LOOP run {stale['id']} has been active for {age_seconds}s; stale threshold is {MAX_IN_PROGRESS_AGE_SECONDS}s",
        }
    if active and latest not in active:
        return {
            "status": "BLOCKED", "outcome": "ACTIVE_RUN_NOT_LATEST", "active_run_count": len(active),
            "latest_run_id": latest["id"], "latest_run_attempt": latest["run_attempt"],
            "latest_conclusion": latest.get("conclusion"),
            "detail": "An active Main LOOP run is older than a newer completed record; run ordering is inconsistent",
        }
    if latest["status"] in {"queued", "in_progress"}:
        return {
            "status": "PASS", "outcome": "ACTIVE" if latest["status"] == "in_progress" else "QUEUED", "active_run_count": len(active),
            "latest_run_id": latest["id"], "latest_run_attempt": latest["run_attempt"],
            "latest_conclusion": latest.get("conclusion"),
            "detail": "Latest Main LOOP run state verified; this is activity evidence only",
        }

    conclusion = latest.get("conclusion")
    if conclusion in FAILED_CONCLUSIONS or not isinstance(conclusion, str):
        status, outcome = "BLOCKED", "FAILED"
        detail = f"Latest Main LOOP run completed with unhealthy or missing conclusion: {conclusion!r}"
    elif conclusion == "success":
        status, outcome = "PASS", "WORKFLOW_SUCCESS"
        detail = "Latest Main LOOP workflow succeeded; task-level result still requires separate evidence"
    elif conclusion in {"skipped", "neutral"}:
        status, outcome = "INFO", "NOT_EXECUTED"
        detail = f"Latest Main LOOP run conclusion is {conclusion}; it is not counted as task execution success"
    else:
        status, outcome = "BLOCKED", "UNVERIFIED"
        detail = f"Latest Main LOOP conclusion is not allowlisted: {conclusion!r}"
    return {
        "status": status, "outcome": outcome, "active_run_count": len(active),
        "latest_run_id": latest["id"], "latest_run_attempt": latest["run_attempt"],
        "latest_conclusion": conclusion, "detail": detail,
    }

def evaluate(
    runs_payload: Any,
    durable_payload: Any,
    *,
    run_id: str,
    head_sha: str,
    started_at: str,
    state_meta: Any = None,
    state_response: Any = None,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []

    runs_payload = normalize_actions_runs(runs_payload)
    runs_shape_ok = (
        isinstance(runs_payload, dict)
        and isinstance(runs_payload.get("workflow_runs"), list)
        and all(isinstance(item, dict) for item in runs_payload["workflow_runs"])
    )
    runs_have_valid_workflow_ids = runs_shape_ok and all(
        type(item.get("workflow_id")) is int and item["workflow_id"] > 0
        for item in runs_payload["workflow_runs"]
    )
    runs_ok = runs_shape_ok and runs_have_valid_workflow_ids
    checks["actions_api"] = {
        "status": "PASS" if runs_ok else "BLOCKED",
        "detail": (
            "Recent workflow runs retrieved with valid workflow IDs"
            if runs_ok else "Actions evidence missing, malformed, or missing a valid workflow_id"
        ),
    }
    if not runs_ok:
        reasons.append("Actions API evidence unavailable or malformed (workflow_id validation failed)")

    state_ok = isinstance(durable_payload, dict)
    recovery = durable_payload.get("recovery_ai") if state_ok else None
    checkpoint = recovery.get("checkpoint") if isinstance(recovery, dict) else None
    checkpoint_ok = checkpoint is None or (
        isinstance(checkpoint, dict)
        and checkpoint.get("verified") is True
        and isinstance(checkpoint.get("task_id"), str)
        and bool(checkpoint.get("task_id"))
        and isinstance(checkpoint.get("checkpoint_id"), str)
        and bool(checkpoint.get("checkpoint_id"))
        and parse_utc(checkpoint.get("saved_at")) is not None
    )
    recovery_ok = (
        isinstance(recovery, dict)
        and type(recovery.get("schema_version")) is int
        and recovery.get("schema_version") == 1
        and isinstance(recovery.get("tasks"), dict)
        and "checkpoint" in recovery
        and checkpoint_ok
    )
    checks["durable_state"] = {
        "status": "PASS" if state_ok else "BLOCKED",
        "detail": "Durable loop state parsed" if state_ok else "Durable state missing or malformed",
    }
    checks["recovery_schema"] = {
        "status": "PASS" if recovery_ok else "BLOCKED",
        "detail": (
            "Recovery AI schema and optional checkpoint validated"
            if recovery_ok else "Recovery AI schema, task map, or checkpoint invalid"
        ),
    }
    if not state_ok or not recovery_ok:
        reasons.append("Durable Recovery AI evidence unavailable or invalid")

    started_dt = parse_utc(started_at)
    recovery_updated_at = (
        parse_utc(recovery.get("state_updated_at"))
        if isinstance(recovery, dict) else None
    )
    recovery_age_seconds = None
    recovery_freshness_errors: list[str] = []
    if recovery_updated_at is None:
        recovery_freshness_errors.append("Recovery AI state_updated_at missing or invalid")
    if started_dt is None:
        recovery_freshness_errors.append("monitor start timestamp missing or invalid")
    if recovery_updated_at is not None and started_dt is not None:
        recovery_age_seconds = int((started_dt - recovery_updated_at).total_seconds())
        if recovery_age_seconds < -MAX_FUTURE_CLOCK_SKEW_SECONDS:
            recovery_freshness_errors.append("Recovery AI update timestamp is too far in the future")
        elif recovery_age_seconds > MAX_STATE_AGE_HOURS * 3600:
            recovery_freshness_errors.append(
                f"Recovery AI state is older than {MAX_STATE_AGE_HOURS} hours"
            )
    recovery_freshness_ok = not recovery_freshness_errors
    checks["recovery_freshness"] = {
        "status": "PASS" if recovery_freshness_ok else "BLOCKED",
        "state_updated_at": recovery.get("state_updated_at") if isinstance(recovery, dict) else None,
        "age_seconds": recovery_age_seconds,
        "max_age_hours": MAX_STATE_AGE_HOURS,
        "detail": "Recovery AI document update timestamp is fresh"
                  if recovery_freshness_ok else "; ".join(recovery_freshness_errors),
    }
    if not recovery_freshness_ok:
        reasons.extend(recovery_freshness_errors)

    meta_ok = isinstance(state_meta, dict)
    branch_sha = state_meta.get("branch_tip_sha") if meta_ok else None
    commit_sha = state_meta.get("state_commit_sha") if meta_ok else None
    commit_time = parse_utc(state_meta.get("state_commit_timestamp")) if meta_ok else None
    response_blob_sha = state_response.get("sha") if isinstance(state_response, dict) else None
    calculated_blob_sha = github_blob_sha(state_response)
    declared_blob_sha = state_meta.get("contents_blob_sha") if meta_ok else None
    provenance_errors: list[str] = []

    if not isinstance(branch_sha, str) or not SHA_RE.fullmatch(branch_sha):
        provenance_errors.append("state branch tip SHA missing or invalid")
    if not isinstance(commit_sha, str) or not SHA_RE.fullmatch(commit_sha):
        provenance_errors.append("pinned state commit SHA missing or invalid")
    elif branch_sha != commit_sha:
        provenance_errors.append("state branch tip and pinned commit SHA differ")
    if commit_time is None:
        provenance_errors.append("state commit timestamp missing or invalid")
    if not isinstance(response_blob_sha, str) or not SHA_RE.fullmatch(response_blob_sha):
        provenance_errors.append("Contents API blob SHA missing or invalid")
    if declared_blob_sha != response_blob_sha:
        provenance_errors.append("declared and Contents API blob SHAs differ")
    if calculated_blob_sha is None or calculated_blob_sha != response_blob_sha:
        provenance_errors.append("Git blob SHA does not match downloaded state bytes")
    if started_dt is None:
        provenance_errors.append("monitor start timestamp missing or invalid")

    state_age_seconds = None
    if commit_time is not None and started_dt is not None:
        state_age_seconds = int((started_dt - commit_time).total_seconds())
        if state_age_seconds < -MAX_FUTURE_CLOCK_SKEW_SECONDS:
            provenance_errors.append("state commit timestamp is too far in the future")
        elif state_age_seconds > MAX_STATE_AGE_HOURS * 3600:
            provenance_errors.append(
                f"durable state is older than {MAX_STATE_AGE_HOURS} hours"
            )

    provenance_ok = not provenance_errors
    checks["state_provenance"] = {
        "status": "PASS" if provenance_ok else "BLOCKED",
        "branch_tip_sha": branch_sha if isinstance(branch_sha, str) else None,
        "state_commit_sha": commit_sha if isinstance(commit_sha, str) else None,
        "contents_blob_sha": response_blob_sha if isinstance(response_blob_sha, str) else None,
        "state_age_seconds": state_age_seconds,
        "max_state_age_hours": MAX_STATE_AGE_HOURS,
        "detail": "Pinned state source and Git blob integrity verified" if provenance_ok
                  else "; ".join(provenance_errors),
    }
    if not provenance_ok:
        reasons.extend(provenance_errors)

    held_ids: list[str] = []
    review_ids: list[str] = []
    malformed_ids: list[str] = []
    if recovery_ok:
        for task_id, record in recovery["tasks"].items():
            if not isinstance(record, dict):
                malformed_ids.append(str(task_id))
                continue
            if "held" in record and type(record["held"]) is not bool:
                malformed_ids.append(str(task_id))
            if "resume_requires_review" in record and type(record["resume_requires_review"]) is not bool:
                malformed_ids.append(str(task_id))
            if record.get("held") is True:
                held_ids.append(str(task_id))
            if record.get("resume_requires_review") is True:
                review_ids.append(str(task_id))
    if held_ids or review_ids or malformed_ids:
        checks["recovery_safety"] = {
            "status": "BLOCKED",
            "held_task_count": len(held_ids),
            "resume_review_required_count": len(review_ids),
            "malformed_task_record_count": len(set(malformed_ids)),
            "detail": "Held, review-pending, or malformed task records detected; no state was changed",
        }
        reasons.append("HOLD, pending resume review, or malformed task record detected")
    elif recovery_ok:
        checks["recovery_safety"] = {
            "status": "PASS",
            "held_task_count": 0,
            "resume_review_required_count": 0,
            "malformed_task_record_count": 0,
            "detail": "No held or review-pending task flags detected",
        }
    else:
        checks["recovery_safety"] = {"status": "BLOCKED", "detail": "Cannot evaluate recovery safety"}

    # Queue eligibility and independent human approval require separate, authoritative
    # evidence. This monitor does not infer approval from task catalog fields or labels.
    checks["queue_and_approval"] = {
        "status": "NOT_EVALUATED",
        "detail": "Queue eligibility and independent human approval require a separate authoritative gate; this monitor does not grant execution permission",
    }

    if runs_ok:
        run_evidence = evaluate_main_loop_runs(runs_payload["workflow_runs"], started_dt or datetime.min.replace(tzinfo=timezone.utc))
        checks["main_loop_activity"] = {
            **run_evidence,
            "workflow_id": MAIN_LOOP_WORKFLOW_ID,
        }
        if run_evidence["status"] == "BLOCKED":
            reasons.append("Main LOOP run evidence invalid or unhealthy: " + run_evidence["detail"])
        elif run_evidence["outcome"] == "NO_CHANGE":
            # Absence of a Main LOOP run is not evidence of a healthy cadence.
            # Keep the activity sub-check informational, but fail the overall
            # monitor closed so a missing run cannot be mistaken for PASS.
            reasons.append("No Main LOOP run found; scheduled task activity is unverified")
    else:
        checks["main_loop_activity"] = {
            "status": "BLOCKED",
            "outcome": "UNVERIFIED",
            "workflow_id": MAIN_LOOP_WORKFLOW_ID,
            "active_run_count": None,
            "latest_run_id": None,
            "latest_run_attempt": None,
            "latest_conclusion": None,
            "detail": "Main LOOP activity cannot be verified because Actions run records or workflow IDs are invalid",
        }

    checks["task_execution_evidence"] = {
        "status": "NOT_EVALUATED",
        "detail": "Workflow run metadata cannot prove task execution; a separately validated run artifact/JSONL evidence source is required",
    }

    monitor_sha_ok = isinstance(head_sha, str) and bool(SHA_RE.fullmatch(head_sha))
    if not monitor_sha_ok:
        reasons.append("Monitor source HEAD SHA missing or invalid")
    checks["monitor_source"] = {
        "status": "PASS" if monitor_sha_ok else "BLOCKED",
        "detail": "Monitor source HEAD SHA recorded" if monitor_sha_ok else "Monitor source HEAD SHA missing or invalid",
    }

    status = "BLOCKED" if reasons else "PASS"
    return {
        "schema_version": 2,
        "run_id": str(run_id),
        "monitor_head_sha": head_sha if monitor_sha_ok else None,
        "state_branch_tip_sha": branch_sha if isinstance(branch_sha, str) else None,
        "state_commit_sha": commit_sha if isinstance(commit_sha, str) else None,
        "state_blob_sha": response_blob_sha if isinstance(response_blob_sha, str) else None,
        "state_age_seconds": state_age_seconds,
        "recovery_state_updated_at": recovery.get("state_updated_at") if isinstance(recovery, dict) else None,
        "recovery_state_age_seconds": recovery_age_seconds,
        "scheduled_at": None,
        "schedule_expression": "*/30 * * * * (UTC)",
        "started_at": started_at,
        "completed_at": utc_now(),
        "status": status,
        "dispatch_allowed": False,
        "checks": checks,
        "failure_reason": "; ".join(dict.fromkeys(reasons)) or None,
        "limitations": [
            "A PASS is health evidence only and never authorizes task execution.",
            "Queue eligibility and independent human approval are not evaluated by this health monitor and must be enforced by a separate execution gate.",
            "The 24-hour state-age ceiling is a conservative monitoring guard, not a verified normal writer cadence.",
            "Recovery AI state freshness is measured from its own state_updated_at field, separately from the outer Git commit timestamp.",
            "GitHub scheduled events may be delayed or skipped; this report does not imply a missed run succeeded.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-json", required=True)
    parser.add_argument("--state-json", required=True)
    parser.add_argument("--state-meta-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = utc_now()
    runs = load_json(args.runs_json)
    state_response = load_json(args.state_json)
    state_meta = load_json(args.state_meta_json)
    state = decode_github_contents(state_response)
    report = evaluate(
        runs, state,
        run_id=os.environ.get("GITHUB_RUN_ID", "unknown"),
        head_sha=os.environ.get("GITHUB_SHA", ""),
        started_at=started,
        state_meta=state_meta,
        state_response=state_response,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "dispatch_allowed": False,
                      "failure_reason": report["failure_reason"]}, ensure_ascii=False))
    # A BLOCKED report is still written and uploaded by the workflow's
    # always()-guarded summary/artifact steps, but the run must be visibly red.
    # Only a complete health PASS may produce a successful Actions conclusion.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
