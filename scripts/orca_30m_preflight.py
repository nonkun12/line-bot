"""Read-only activation preflight for the unified 30-minute LOOP.

This gate deliberately never authorizes the legacy worker. Phase 3's durable
claim/lease helpers are not yet connected to an executable worker, so a
successful prerequisite check still reports execution_enabled=false.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_REQUIRED_ENV = (
    "ORCA_APPROVAL_JSON",
    "ORCA_APPROVAL_SIGNING_KEY",
    "ORCA_ALLOWED_APPROVERS",
    "ORCA_BUDGET_EVIDENCE_JSON",
    "ORCA_BUDGET_SIGNING_KEY",
    "ORCA_BILLING_ACCOUNT_ID",
    "ORCA_IMPROVEMENT_CYCLE_JSON",
)


def _json_env(name: str) -> Any:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raise ValueError(f"{name.lower()}_missing")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"{name.lower()}_invalid_json") from None


def scheduled_run_is_fresh(created_at: str, *, now: datetime, max_age: timedelta = timedelta(minutes=15)) -> bool:
    """Reject a scheduled run that waited too long in the Actions concurrency queue."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return False
    if created.tzinfo is None or now.tzinfo is None or now.utcoffset() is None:
        return False
    age = now.astimezone(timezone.utc) - created.astimezone(timezone.utc)
    return timedelta(0) <= age <= max_age


def _scheduled_run_freshness(values: Any) -> str | None:
    if values.get("GITHUB_EVENT_NAME") != "schedule":
        return None
    token = values.get("GITHUB_TOKEN", "")
    repository = values.get("GITHUB_REPOSITORY", "")
    run_id = values.get("GITHUB_RUN_ID", "")
    if not token or "/" not in repository or not run_id:
        return "scheduled_run_metadata_unavailable"
    import urllib.error
    import urllib.request
    url = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orca-30m-schedule-freshness",
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(256_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
        return "scheduled_run_metadata_unavailable"
    created_at = payload.get("created_at") if isinstance(payload, dict) else None
    if not scheduled_run_is_fresh(created_at, now=datetime.now(timezone.utc)):
        return "stale_scheduled_run_discarded"
    return None


def inspect_prerequisites(*, env: dict[str, str] | None = None, store: Any = None,
                          now: datetime | None = None) -> dict[str, Any]:
    """Inspect durable prerequisites without writing state or claiming work."""
    values = os.environ if env is None else env
    freshness_error = _scheduled_run_freshness(values)
    if freshness_error:
        return {"status": "BLOCKED", "reason": freshness_error, "execution_enabled": False}
    missing = [name for name in _REQUIRED_ENV if not values.get(name, "").strip()]
    if missing:
        return {
            "status": "BLOCKED",
            "reason": "missing_trusted_gate_configuration:" + ",".join(missing),
            "execution_enabled": False,
        }

    try:
        if store is None:
            from scripts.orca_github_state_store import GitHubStateStore
            store = GitHubStateStore(
                token=values.get("GITHUB_TOKEN", ""),
                repository=values.get("GITHUB_REPOSITORY", ""),
                branch=values.get("ORCA_STATE_BRANCH", "orca-state"),
                path=values.get("ORCA_STATE_PATH", "state/queue.json"),
            )
        snapshot = store.read()
        state = snapshot.state
        if not isinstance(state, dict):
            raise ValueError("durable_state_invalid")
        if state.get("emergency_stop") is not False:
            raise ValueError("emergency_stop_active_or_unverifiable")
        if state.get("global_hold") is not False:
            raise ValueError("global_hold_active_or_unverifiable")
        if state.get("active_lease") is not None:
            raise ValueError("active_lease_present")
        tasks = state.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("queue_tasks_missing_or_invalid")
        queued = [row for row in tasks if isinstance(row, dict) and row.get("status") == "queued"]
        if not queued:
            raise ValueError("no_approved_queued_task")
        task = sorted(queued, key=lambda row: (str(row.get("created_at", "")), str(row.get("task_id", ""))))[0]
        if not isinstance(task.get("task_id"), str) or not isinstance(task.get("request_hash"), str):
            raise ValueError("queued_task_identity_invalid")
        run_id = values.get("GITHUB_RUN_ID", "")
        from scripts.orca_github_runaway_guard import (
            initialize_run_guard, validate_and_consume_claim,
        )
        current_time = now or datetime.now(timezone.utc)
        prospective_state = dict(state)
        prospective_state["run_guard"] = initialize_run_guard(
            state=state, run_id=run_id, now=current_time,
        )
        validate_and_consume_claim(
            state=prospective_state, task_id=task["task_id"], now=current_time,
        )

        from scripts.orca_github_execution_gate import evaluate_execution_gate
        approval = _json_env("ORCA_APPROVAL_JSON") if env is None else json.loads(values["ORCA_APPROVAL_JSON"])
        budget = _json_env("ORCA_BUDGET_EVIDENCE_JSON") if env is None else json.loads(values["ORCA_BUDGET_EVIDENCE_JSON"])
        cycle = _json_env("ORCA_IMPROVEMENT_CYCLE_JSON") if env is None else json.loads(values["ORCA_IMPROVEMENT_CYCLE_JSON"])
        result = evaluate_execution_gate(
            repository=values.get("GITHUB_REPOSITORY", ""),
            queue_state=state,
            task_id=task["task_id"],
            request_hash=task["request_hash"],
            approval=approval,
            approval_signing_key=values["ORCA_APPROVAL_SIGNING_KEY"],
            allowed_approvers=[x.strip() for x in values["ORCA_ALLOWED_APPROVERS"].split(",") if x.strip()],
            consumed_approval_ids=state.get("consumed_approval_ids"),
            budget_evidence=budget,
            budget_signing_key=values["ORCA_BUDGET_SIGNING_KEY"],
            billing_account_id=values["ORCA_BILLING_ACCOUNT_ID"],
            improvement_cycle=cycle,
            now=current_time,
        )
        if result.get("status") != "PASS":
            raise ValueError("execution_gate_not_passed")
    except Exception as exc:
        # Never print exception messages, tokens, signed payloads, or user data.
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).isidentifier() else type(exc).__name__.lower()
        return {"status": "BLOCKED", "reason": reason, "execution_enabled": False}

    # This is intentionally a permanent stop until a real worker boundary
    # revalidates STOP/HOLD/lease/runaway state and consumes the claim atomically.
    return {
        "status": "BLOCKED",
        "reason": "phase3_worker_runtime_not_integrated",
        "preflight": "PASS",
        "execution_enabled": False,
    }


def main() -> int:
    result = inspect_prerequisites()
    line = f"30-minute LOOP activation preflight: {result['status']} ({result['reason']})"
    print(line)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("execution_enabled=false\n")
            handle.write(f"preflight_status={result['status']}\n")
            handle.write(f"preflight_reason={result['reason']}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## 30-minute LOOP activation preflight\n\n")
            handle.write(f"- Result: **{result['status']}**\n")
            handle.write(f"- Reason: `{result['reason']}`\n")
            handle.write("- Execution enabled: **false**\n")
            handle.write("- Legacy task worker: **not invoked**\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
