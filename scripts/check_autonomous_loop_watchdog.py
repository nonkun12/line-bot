"""Verify that each scheduled autonomous-development slot executed and was audited."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from agents.sheets.autonomous_ledger import (
    HEADERS,
    LEDGER_RANGE,
    _resolved_sheet,
    _sheet_scan_range,
)
from agents.sheets.client import GoogleSheetsClient

JST = ZoneInfo("Asia/Tokyo")
SLOT_HOURS = (4, 10, 16, 22)
SLOT_MINUTE = 30


def github_json(url: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def expected_slot(now: datetime) -> datetime:
    local = now.astimezone(JST).replace(second=0, microsecond=0)
    candidates = []
    for hour in SLOT_HOURS:
        candidate = local.replace(hour=hour, minute=SLOT_MINUTE)
        if candidate <= local:
            candidates.append(candidate)
    if candidates:
        return max(candidates)
    return (local - timedelta(days=1)).replace(hour=SLOT_HOURS[-1], minute=SLOT_MINUTE)


def find_scheduled_run(repo: str, slot: datetime) -> dict | None:
    workflow = "distributed-autonomous-loop.yml"
    data = github_json(
        "https://api.github.com/repos/"
        + quote(repo, safe="/")
        + f"/actions/workflows/{workflow}/runs?event=schedule&per_page=20"
    )
    window_end = slot + timedelta(minutes=120)
    window_start = slot - timedelta(minutes=20)
    for run in data.get("workflow_runs", []):
        if run.get("name") != "Distributed Autonomous Development Loop" or run.get("event") != "schedule":
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(JST)
        if window_start <= created <= window_end:
            return run
    return None


def find_ledger_record(client: GoogleSheetsClient, run_id: str) -> tuple[str, dict[str, str] | None]:
    """Find a row through the run_id column beside the ledger headers."""
    sheet = _resolved_sheet(client)
    rows = client.read_rows(_sheet_scan_range(sheet))
    starts = [
        start
        for row in rows
        if isinstance(row, list) and len(row) >= len(HEADERS)
        for start in range(len(row) - len(HEADERS) + 1)
        if row[start:start + len(HEADERS)] == HEADERS
    ]
    if len(starts) != 1:
        state = "missing" if not starts else "ambiguous"
        raise RuntimeError(f"Google Sheets ledger headers on {sheet!r} are {state}")

    start = starts[0]
    run_id_column = start + HEADERS.index("run_id")
    matches = [
        row[start:start + len(HEADERS)]
        for row in rows
        if isinstance(row, list)
        and len(row) > run_id_column
        and str(row[run_id_column]) == run_id
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Google Sheets has duplicate ledger rows for run_id={run_id}")
    if not matches:
        return sheet, None
    return sheet, dict(zip(HEADERS, map(str, matches[0])))


def main() -> int:
    now = datetime.now(timezone.utc)
    slot = expected_slot(now)
    repo = os.environ["GITHUB_REPOSITORY"]
    problems: list[str] = []
    run = find_scheduled_run(repo, slot)
    ledger_tab = None
    ledger_record = None

    if run is None:
        problems.append(f"scheduled run missing for {slot.isoformat()}")
    else:
        run_id = str(run["id"])
        if run.get("status") != "completed":
            problems.append(f"distributed loop run is not complete: {run.get('status')}")
        elif run.get("conclusion") != "success":
            problems.append(f"distributed loop run conclusion={run.get('conclusion')}")
        try:
            client = GoogleSheetsClient()
            ledger_tab, ledger_record = find_ledger_record(client, run_id)
            if ledger_record is None:
                problems.append(f"Sheets audit row missing for run_id={run_id}")
            else:
                ledger_result = ledger_record.get("tests_result", "")
                if run.get("conclusion") == "success" and ledger_result not in {"PASS", "NO_CHANGE", "NO_TASKS"}:
                    problems.append(
                        f"Sheets result={ledger_result or 'empty'} conflicts with successful run_id={run_id}"
                    )
                recorded_at = datetime.fromisoformat(
                    ledger_record["timestamp"].replace("Z", "+00:00")
                )
                run_started = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
                run_updated = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
                if not run_started - timedelta(minutes=1) <= recorded_at <= run_updated + timedelta(minutes=1):
                    problems.append(f"Sheets audit timestamp is outside run window for run_id={run_id}")
        except Exception as exc:
            problems.append(f"Sheets audit check failed: {type(exc).__name__}: {exc}")

    result = {
        "ok": not problems,
        "expected_slot": slot.isoformat(),
        "run_id": str(run["id"]) if run else None,
        "run_status": run.get("status") if run else None,
        "run_conclusion": run.get("conclusion") if run else None,
        "run_created_at": run.get("created_at") if run else None,
        "ledger_range": LEDGER_RANGE,
        "ledger_tab": ledger_tab,
        "ledger_result": ledger_record.get("tests_result") if ledger_record else None,
        "tasks_processed": 0 if ledger_record and ledger_record.get("tests_result") == "NO_TASKS" else (
            1 if ledger_record and ledger_record.get("tests_result") in {"PASS", "NO_CHANGE"} else None
        ),
        "problems": problems,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
