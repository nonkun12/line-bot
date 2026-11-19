"""Fail-closed monthly GitHub Actions minute budget gate.

The gate measures all started jobs visible in this repository for the current
UTC calendar month. It is a repository-local guard, not an account-wide billing
API; the configured ceiling is deliberately below the user's 2,000-minute stop.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("job timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("job timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("job timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def calculate_used_minutes(jobs: list[dict[str, Any]], *, now: datetime) -> int:
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list")
    if now.tzinfo is None:
        raise ValueError("now must include timezone")
    now_utc = now.astimezone(timezone.utc)
    month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = 0
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("job record is invalid")
        started = job.get("started_at")
        if started is None:
            continue
        start_dt = _parse_time(started)
        end_dt = _parse_time(job["completed_at"]) if job.get("completed_at") else now_utc
        if end_dt < start_dt:
            raise ValueError("job end precedes start")
        # Count only the portion within the current UTC month.
        effective_start = max(start_dt, month_start)
        seconds = max(0.0, (end_dt - effective_start).total_seconds())
        # GitHub rounds billable job time up to whole minutes per job.
        if seconds:
            total += math.ceil(seconds / 60)
    return total


def evaluate_budget(jobs: list[dict[str, Any]], *, budget_minutes: int, now: datetime) -> dict[str, Any]:
    if type(budget_minutes) is not int or not 1 <= budget_minutes <= 2000:
        raise ValueError("budget must be an integer from 1 to 2000")
    used = calculate_used_minutes(jobs, now=now)
    return {
        "allowed": used < budget_minutes,
        "used_minutes": used,
        "budget_minutes": budget_minutes,
        "remaining_minutes": max(0, budget_minutes - used),
        "scope": "this_repository_visible_actions_jobs",
        "reason": "within_repository_budget" if used < budget_minutes else "repository_budget_exhausted",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-jsonl", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=int, default=1800)
    args = parser.parse_args()
    try:
        rows = [
            json.loads(line)
            for line in args.jobs_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        result = evaluate_budget(
            rows,
            budget_minutes=args.budget_minutes,
            now=datetime.now(timezone.utc),
        )
    except Exception as exc:
        print(json.dumps({"allowed": False, "reason": "budget_evidence_invalid", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
