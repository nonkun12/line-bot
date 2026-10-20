"""Verify that each distributed-loop schedule slot executed a verified task and was audited."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from agents.sheets.autonomous_ledger import (
    HEADERS,
    _resolved_sheet,
    _sheet_scan_range,
)
from agents.sheets.client import GoogleSheetsClient

JST = ZoneInfo("Asia/Tokyo")
SLOT_HOURS = (4, 10, 16, 22)
SLOT_MINUTE = 30
INVALID_TASK_IDS = {"", "NOT_RUN", "QUEUE_EMPTY", "QUEUE_EXHAUSTED_NO_TASKS"}


def github_json(url: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def expected_slot(now: datetime) -> datetime:
    local = now.astimezone(JST).replace(second=0, microsecond=0)
    candidates = [
        local.replace(hour=hour, minute=SLOT_MINUTE)
        for hour in SLOT_HOURS
        if local.replace(hour=hour, minute=SLOT_MINUTE) <= local
    ]
    if candidates:
        return max(candidates)
    return (local - timedelta(days=1)).replace(
        hour=SLOT_HOURS[-1], minute=SLOT_MINUTE
    )


def find_scheduled_run(repo: str, slot: datetime) -> dict | None:
    workflow = "distributed-autonomous-loop.yml"
    data = github_json(
        "https://api.github.com/repos/"
        + quote(repo, safe="/")
        + f"/actions/workflows/{workflow}/runs?event=schedule&per_page=20"
    )
    # GitHub Actions may delay scheduled workflows by more than four hours.
    # Allow up to 5h30m, while keeping the window strictly shorter than the
    # six-hour cadence so a delayed run cannot be attributed to the next slot.
    window_end = slot + timedelta(minutes=330)
    window_start = slot - timedelta(minutes=10)
    for run in data.get("workflow_runs", []):
        if run.get("name") != "Distributed Autonomous Development Loop" or run.get("event") != "schedule":
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(JST)
        if window_start <= created <= window_end:
            return run
    return None


def _ledger_rows(client: GoogleSheetsClient) -> tuple[list[list], int, int]:
    """Return rows, header row index, and zero-based header start column."""
    sheet = _resolved_sheet(client)
    rows = client.read_rows(_sheet_scan_range(sheet))
    width = len(HEADERS)
    header_locations: list[tuple[int, int]] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        for start in range(0, len(row) - width + 1):
            if row[start:start + width] == HEADERS:
                header_locations.append((row_index, start))
    if not header_locations:
        raise RuntimeError(f"Google Sheets ledger headers not found on {sheet!r}")
    if len(header_locations) != 1:
        raise RuntimeError(f"Ambiguous Google Sheets ledger headers on {sheet!r}: {header_locations!r}")
    header_row, start_column = header_locations[0]
    return rows, header_row, start_column



def run_is_pending_within_grace(run: dict, slot: datetime, now: datetime) -> bool:
    """Treat active runs as pending only during the first 90 minutes after a slot."""
    if run.get("status") not in {"queued", "in_progress"}:
        return False
    elapsed = now.astimezone(JST) - slot.astimezone(JST)
    return timedelta(0) <= elapsed <= timedelta(minutes=90)


def has_audit_row(client: GoogleSheetsClient, run_id: str) -> bool:
    """Find this run ID under the ledger's run_id header, not a hard-coded column."""
    rows, header_row, start_column = _ledger_rows(client)
    run_id_column = start_column + HEADERS.index("run_id")
    return any(
        isinstance(row, list)
        and len(row) > run_id_column
        and str(row[run_id_column]) == str(run_id)
        for row in rows[header_row + 1:]
    )


def audit_row_outcome(client: GoogleSheetsClient, run_id: str) -> tuple[bool, str]:
    """Require a real task and a PASS safety gate; workflow success alone is insufficient."""
    rows, header_row, start_column = _ledger_rows(client)
    width = len(HEADERS)
    positions = {name: HEADERS.index(name) for name in (
        "run_id", "task_id", "base_sha", "produced_sha", "safety_gate_result", "verification_result",
        "tests_result", "blocked_failed_reason",
    )}
    matching = []
    for row in rows[header_row + 1:]:
        if not isinstance(row, list) or len(row) <= start_column + positions["run_id"]:
            continue
        values = row[start_column:start_column + width]
        if str(values[positions["run_id"]]) == str(run_id):
            matching.append(values)
    if not matching:
        return False, f"Sheets audit row missing for run_id={run_id}"
    if len(matching) != 1:
        return False, f"Ambiguous Sheets audit rows for run_id={run_id}"
    values = matching[0]
    task_id = str(values[positions["task_id"]]).strip()
    if re.sub(r"[^A-Z0-9]+", "_", task_id.upper()).strip("_") in INVALID_TASK_IDS or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", task_id):
        reason = str(values[positions["blocked_failed_reason"]]).strip() or "invalid_or_missing_task_id"
        return False, f"scheduled workflow did not execute a valid task: run_id={run_id} task_id={task_id or '(empty)'} reason={reason}"
    gate = str(values[positions["safety_gate_result"]]).strip().upper()
    if gate != "PASS":
        reason = str(values[positions["blocked_failed_reason"]]).strip() or "safety_gate_not_pass"
        return False, f"scheduled task did not pass Safety Gate: run_id={run_id} task_id={task_id} gate={gate or '(empty)'} reason={reason}"
    verification = str(values[positions["verification_result"]]).strip().upper()
    if verification not in {"PASS", "NO_CHANGE"}:
        return False, f"scheduled task verification is not successful: run_id={run_id} task_id={task_id} verification={verification or '(empty)'}"
    tests = str(values[positions["tests_result"]]).strip().upper()
    if tests not in {"PASS", "NO_CHANGE"}:
        return False, f"scheduled task tests are not successful: run_id={run_id} task_id={task_id} tests={tests or '(empty)'}"
    base_sha = str(values[positions["base_sha"]]).strip()
    produced_sha = str(values[positions["produced_sha"]]).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha):
        return False, f"scheduled task base SHA is missing or malformed: run_id={run_id} task_id={task_id}"
    if not re.fullmatch(r"[0-9a-fA-F]{40}", produced_sha):
        return False, f"scheduled task produced SHA is missing or malformed: run_id={run_id} task_id={task_id}"
    return True, "verified_task_passed"


def main() -> int:
    now = datetime.now(timezone.utc)
    slot = expected_slot(now)
    repo = os.environ["GITHUB_REPOSITORY"]
    problems: list[str] = []
    run = find_scheduled_run(repo, slot)
    pending = False

    if run is None:
        problems.append(f"distributed scheduled run missing for {slot.isoformat()}")
    else:
        run_id = str(run["id"])
        if run.get("status") in {"queued", "in_progress"}:
            pending = run_is_pending_within_grace(run, slot, now)
            if not pending:
                problems.append(
                    f"distributed scheduled run still active after grace: "
                    f"run_id={run_id} status={run.get('status')}"
                )
        else:
            if run.get("conclusion") != "success":
                problems.append(
                    f"distributed scheduled run did not succeed: "
                    f"run_id={run_id} conclusion={run.get('conclusion')}"
                )
            try:
                client = GoogleSheetsClient()
                ok, outcome = audit_row_outcome(client, run_id)
                if not ok:
                    problems.append(outcome)
            except Exception as exc:
                problems.append(f"Sheets audit check failed: {type(exc).__name__}: {exc}")

    result = {
        "ok": not problems,
        "pending": pending,
        "expected_slot": slot.isoformat(),
        "run_id": str(run["id"]) if run else None,
        "run_status": run.get("status") if run else None,
        "run_conclusion": run.get("conclusion") if run else None,
        "problems": problems,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
