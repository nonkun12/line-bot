"""Verify that each distributed-loop schedule slot executed and was audited."""
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
    # GitHub scheduled events can start a little late; inspect the slot and
    # the following two hours, but never match a different scheduled slot.
    window_end = slot + timedelta(minutes=120)
    window_start = slot - timedelta(minutes=10)
    for run in data.get("workflow_runs", []):
        if run.get("name") != "Distributed Autonomous Development Loop" or run.get("event") != "schedule":
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(JST)
        if window_start <= created <= window_end:
            return run
    return None


def has_audit_row(client: GoogleSheetsClient, run_id: str) -> bool:
    """Find this run ID under the ledger's run_id header, not a hard-coded column."""
    sheet = _resolved_sheet(client)
    rows = client.read_rows(_sheet_scan_range(sheet))
    header_locations: list[tuple[int, int]] = []
    width = len(HEADERS)
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
    run_id_column = start_column + HEADERS.index("run_id")
    return any(
        isinstance(row, list)
        and len(row) > run_id_column
        and str(row[run_id_column]) == str(run_id)
        for row in rows[header_row + 1:]
    )


def main() -> int:
    now = datetime.now(timezone.utc)
    slot = expected_slot(now)
    repo = os.environ["GITHUB_REPOSITORY"]
    problems: list[str] = []
    run = find_scheduled_run(repo, slot)

    if run is None:
        problems.append(f"distributed scheduled run missing for {slot.isoformat()}")
    else:
        run_id = str(run["id"])
        if run.get("status") not in {"queued", "in_progress"}:
            if run.get("conclusion") != "success":
                problems.append(
                    f"distributed scheduled run did not succeed: "
                    f"run_id={run_id} conclusion={run.get('conclusion')}"
                )
            try:
                client = GoogleSheetsClient()
                if not has_audit_row(client, run_id):
                    problems.append(f"Sheets audit row missing for run_id={run_id}")
            except Exception as exc:
                problems.append(f"Sheets audit check failed: {type(exc).__name__}: {exc}")

    result = {
        "ok": not problems,
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
