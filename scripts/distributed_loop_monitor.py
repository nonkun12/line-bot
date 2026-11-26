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


def evaluate_schedule_slots(
    runs: list[dict[str, Any]],
    started_at: str,
    grace_minutes: int = 15,
    scheduler_decisions: Any = None,
) -> dict[str, Any]:
    """Check expected slots using immutable, run-ID-bound scheduler decision artifacts."""
    from datetime import timedelta

    now = parse_utc(started_at)
    if now is None:
        return {"status": "BLOCKED", "checked_slots": 0, "missing_slots": [],
                "detail": "invalid monitor timestamp"}
    scheduler_id, loop_id = 419124193, 369890295
    schedulers = [r for r in runs if r.get("workflow_id") == scheduler_id]
    loops = [r for r in runs if r.get("workflow_id") == loop_id]
    decisions = scheduler_decisions if isinstance(scheduler_decisions, dict) else {}
    cursor = now.replace(second=0, microsecond=0)
    cursor -= timedelta(minutes=(cursor.minute - 19) % 30)
    missing, pending, confirmed, safe_skips, held_slots = [], [], [], [], []
    allowed = {
        "DISPATCHED", "SKIPPED_ACTIVE_LOOP", "SKIPPED_KILL_SWITCH",
        "SKIPPED_BILLING_GUARD", "DISPATCH_UNCONFIRMED",
    }

    while cursor >= now - timedelta(hours=24):
        deadline = cursor + timedelta(minutes=grace_minutes)
        if now < deadline:
            pending.append(cursor.isoformat())
        else:
            matches = [
                r for r in schedulers
                if r.get("event") == "schedule"
                and (created := parse_utc(r.get("created_at"))) is not None
                and cursor <= created <= deadline
            ]
            if not matches:
                missing.append({"slot": cursor.isoformat(), "status": "SCHEDULER_MISSING"})
            else:
                scheduler = min(
                    matches,
                    key=lambda r: abs((parse_utc(r["created_at"]) - cursor).total_seconds()),
                )
                scheduler_run_id = str(scheduler.get("id", ""))
                envelope = decisions.get(scheduler_run_id)
                if not isinstance(envelope, dict) or envelope.get("artifact_status") != "available":
                    missing.append({
                        "slot": cursor.isoformat(),
                        "status": "LEGACY_UNVERIFIED" if envelope is None else ("DECISION_ARTIFACT_INVALID" if envelope.get("artifact_status") == "invalid" else "DECISION_ARTIFACT_UNAVAILABLE"),
                        "scheduler_run_id": scheduler.get("id"),
                    })
                    cursor -= timedelta(minutes=30)
                    continue
                record = envelope.get("record")
                decision = record.get("decision") if isinstance(record, dict) else None
                created_at = parse_utc(record.get("created_at")) if isinstance(record, dict) else None
                valid_record = (
                    isinstance(record, dict)
                    and type(record.get("schema_version")) is int\n                    and record.get("schema_version") == 1
                    and str(record.get("scheduler_run_id", "")) == scheduler_run_id
                    and str(record.get("request_id", "")) == scheduler_run_id
                    and type(record.get("run_attempt")) is int
                    and record.get("run_attempt") == scheduler.get("run_attempt", 1)
                    and record.get("execution_approval") == "DENY"
                    and record.get("policy_dispatch") == "30m_scheduler"
                    and record.get("head_sha") == scheduler.get("head_sha")
                    and created_at is not None
                    and created_at >= (parse_utc(scheduler.get("run_started_at") or scheduler["created_at"]) - timedelta(minutes=5))
                    and created_at <= now + timedelta(minutes=5)
                    and (created_at - parse_utc(scheduler.get("run_started_at") or scheduler["created_at"])).total_seconds() <= 900
                    and decision in allowed
                )
                if not valid_record:
                    missing.append({
                        "slot": cursor.isoformat(), "status": "DECISION_ARTIFACT_INVALID",
                        "scheduler_run_id": scheduler.get("id"),
                    })
                elif decision == "DISPATCH_UNCONFIRMED":
                    missing.append({
                        "slot": cursor.isoformat(), "status": "DISPATCH_UNCONFIRMED",
                        "scheduler_run_id": scheduler.get("id"),
                    })
                elif decision == "DISPATCHED":
                    child_id = record.get("child_loop_run_id")
                    child = next((
                        r for r in loops
                        if str(r.get("id", "")) == str(child_id)
                        and f"request_id={scheduler_run_id}" in str(
                            r.get("display_title") or r.get("name") or ""
                        )
                    ), None)
                    if child is None or not child_id:
                        missing.append({
                            "slot": cursor.isoformat(), "status": "DISPATCH_UNCONFIRMED",
                            "scheduler_run_id": scheduler.get("id"),
                        })
                    else:
                        confirmed.append({
                            "slot": cursor.isoformat(),
                            "scheduler_run_id": scheduler.get("id"),
                            "loop_run_id": child.get("id"),
                            "loop_status": child.get("status"),
                            "loop_conclusion": child.get("conclusion"),
                        })
                elif decision == "SKIPPED_ACTIVE_LOOP":
                    active_id = record.get("active_loop_run_id")
                    active_status = record.get("active_loop_status_at_decision")
                    active_loop = next((r for r in loops if str(r.get("id", "")) == str(active_id)), None)
                    active_created = parse_utc(record.get("active_loop_created_at"))
                    actual_created = parse_utc(active_loop.get("created_at")) if active_loop else None
                    scheduler_created = parse_utc(scheduler.get("created_at"))
                    completion_time = (
                        parse_utc(active_loop.get("completed_at") or active_loop.get("updated_at"))
                        if active_loop else None
                    )
                    was_active_at_decision = (
                        bool(active_id)
                        and active_status in {"queued", "in_progress"}
                        and record.get("active_loop_workflow_id") == loop_id
                        and active_loop is not None
                        and active_created is not None
                        and actual_created is not None
                        and active_created == actual_created
                        and scheduler_created is not None
                        and active_created <= scheduler_created
                        and (
                            active_loop.get("status") in {"queued", "in_progress"}
                            or (completion_time is not None and completion_time > scheduler_created)
                        )
                    )
                    if not was_active_at_decision:
                        missing.append({
                            "slot": cursor.isoformat(), "status": "UNVERIFIED_ACTIVE_LOOP_SKIP",
                            "scheduler_run_id": scheduler.get("id"),
                        })
                    else:
                        safe_skips.append({
                            "slot": cursor.isoformat(), "scheduler_run_id": scheduler.get("id"),
                            "decision": decision, "active_loop_run_id": active_id,
                        })
                elif decision == "SKIPPED_KILL_SWITCH":
                    if (
                        record.get("kill_switch_active") is True
                        and record.get("skip_reason") in {"CONTROL_TOWER_KILL_SWITCH", "STOP_FILE"}
                    ):
                        safe_skips.append({
                            "slot": cursor.isoformat(), "scheduler_run_id": scheduler.get("id"),
                            "decision": decision, "reason": record.get("skip_reason"),
                        })
                        held_slots.append({
                            "slot": cursor.isoformat(), "scheduler_run_id": scheduler.get("id"),
                            "decision": decision,
                        })
                    else:
                        missing.append({
                            "slot": cursor.isoformat(), "status": "UNVERIFIED_KILL_SWITCH_SKIP",
                            "scheduler_run_id": scheduler.get("id"),
                        })
                elif decision == "SKIPPED_BILLING_GUARD":
                    if record.get("repository_visibility") in {"private", "internal"}:
                        safe_skips.append({
                            "slot": cursor.isoformat(), "scheduler_run_id": scheduler.get("id"),
                            "decision": decision, "reason": "repository_visibility_not_public",
                        })
                        held_slots.append({
                            "slot": cursor.isoformat(), "scheduler_run_id": scheduler.get("id"),
                            "decision": decision,
                        })
                    else:
                        missing.append({
                            "slot": cursor.isoformat(), "status": "UNVERIFIED_BILLING_GUARD_SKIP",
                            "scheduler_run_id": scheduler.get("id"),
                        })
                else:
                    missing.append({
                        "slot": cursor.isoformat(), "status": "UNSUPPORTED_DECISION",
                        "scheduler_run_id": scheduler.get("id"),
                    })
        cursor -= timedelta(minutes=30)

    status = "BLOCKED" if missing else ("HOLD" if held_slots else ("PENDING" if pending else "PASS"))
    return {
        "status": status,
        "checked_slots": len(confirmed) + len(safe_skips) + len(missing) + len(pending),
        "confirmed_slots": confirmed,
        "safe_skips": safe_skips,
        "held_slots": held_slots,
        "missing_slots": missing,
        "pending_slots": pending,
        "grace_minutes": grace_minutes,
        "detail": "30-minute scheduler slots verified against run-ID-bound decision artifacts",
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
    schedule_evidence: bool = False,
    scheduler_decisions: Any = None,
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
            "status": "BLOCKED" if malformed_ids else "HOLD",
            "held_task_count": len(held_ids),
            "resume_review_required_count": len(review_ids),
            "malformed_task_record_count": len(set(malformed_ids)),
            "detail": "Held, review-pending, or malformed task records detected; no state was changed",
        }
        if malformed_ids:
            reasons.append("Malformed recovery task record detected")
        else:
            reasons.append("HOLD: held or pending-review tasks remain safely gated")
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

    if schedule_evidence:
        slot_report = evaluate_schedule_slots(
            runs_payload["workflow_runs"] if runs_ok else [],
            started_at,
            scheduler_decisions=scheduler_decisions,
        )
        checks["schedule_slot_coverage"] = slot_report
        if slot_report["status"] == "BLOCKED":
            reasons.append("Expected 30-minute scheduler slot missing or scheduler decision evidence unverified")
        elif slot_report["status"] == "HOLD":
            reasons.append("HOLD: scheduler intentionally stopped by kill switch or billing guard")

    # Queue eligibility and independent human approval require separate, authoritative
    # evidence. This monitor does not infer approval from task catalog fields or labels.
    checks["queue_and_approval"] = {
        "status": "NOT_EVALUATED",
        "detail": "Queue eligibility and independent human approval require a separate authoritative gate; this monitor does not grant execution permission",
    }

    if runs_ok:
        active = [
            item for item in runs_payload["workflow_runs"]
            if item.get("workflow_id") == 369890295
            and item.get("status") in {"queued", "in_progress"}
        ]
        checks["main_loop_activity"] = {
            "status": "PASS" if active else "INFO",
            "outcome": "ACTIVE" if active else "NO_CHANGE",
            "workflow_id": 369890295,
            "active_run_count": len(active),
            "detail": (
                "Main LOOP workflow activity confirmed by fixed workflow ID; monitor did not dispatch or cancel anything"
                if active else "No active Main LOOP run observed for the fixed workflow ID; no dispatch was attempted"
            ),
        }
    else:
        checks["main_loop_activity"] = {
            "status": "BLOCKED",
            "outcome": "UNVERIFIED",
            "workflow_id": 369890295,
            "active_run_count": None,
            "detail": "Main LOOP activity cannot be verified because Actions run records or workflow IDs are invalid",
        }

    monitor_sha_ok = isinstance(head_sha, str) and bool(SHA_RE.fullmatch(head_sha))
    if not monitor_sha_ok:
        reasons.append("Monitor source HEAD SHA missing or invalid")
    checks["monitor_source"] = {
        "status": "PASS" if monitor_sha_ok else "BLOCKED",
        "detail": "Monitor source HEAD SHA recorded" if monitor_sha_ok else "Monitor source HEAD SHA missing or invalid",
    }

    only_deliberate_hold = bool(reasons) and all(
        reason.startswith("HOLD:") for reason in reasons
    )
    status = "HOLD" if only_deliberate_hold else ("BLOCKED" if reasons else "PASS")
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
        "schedule_expression": "19,49 * * * * (UTC)",
        "started_at": started_at,
        "completed_at": utc_now(),
        "status": status,
        "dispatch_allowed": False,
        "checks": checks,
        "failure_reason": "; ".join(dict.fromkeys(reasons)) or None,
        "limitations": [
            "PASS and HOLD are health/control outcomes only and never authorize task execution.",
            "HOLD is distinct from system failure only when all evidence/provenance checks pass and no malformed records are present.",
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
    parser.add_argument("--scheduler-decisions-json", required=False)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = utc_now()
    runs = load_json(args.runs_json)
    state_response = load_json(args.state_json)
    state_meta = load_json(args.state_meta_json)
    scheduler_decisions = load_json(args.scheduler_decisions_json) if args.scheduler_decisions_json else None
    state = decode_github_contents(state_response)
    report = evaluate(
        runs, state,
        run_id=os.environ.get("GITHUB_RUN_ID", "unknown"),
        head_sha=os.environ.get("GITHUB_SHA", ""),
        started_at=started,
        state_meta=state_meta,
        state_response=state_response,
        schedule_evidence=True,
        scheduler_decisions=scheduler_decisions,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "dispatch_allowed": False,
                      "failure_reason": report["failure_reason"]}, ensure_ascii=False))
    # A BLOCKED report is still written and uploaded by the workflow's
    # always()-guarded summary/artifact steps, but the run must be visibly red.
    # Only a complete health PASS may produce a successful Actions conclusion.
    return 0 if report["status"] in {"PASS", "HOLD"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
