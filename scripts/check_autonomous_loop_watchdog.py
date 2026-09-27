"""Verify that each scheduled autonomous-development slot executed and was audited."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.sheets.autonomous_ledger import LEDGER_RANGE
from agents.sheets.client import GoogleSheetsClient

JST = ZoneInfo("Asia/Tokyo")
SLOT_HOURS = (3, 15, 21)


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
        candidate = local.replace(hour=hour, minute=5)
        if candidate <= local:
            candidates.append(candidate)
    if candidates:
        return max(candidates)
    return (local - timedelta(days=1)).replace(hour=SLOT_HOURS[-1], minute=5)


def find_scheduled_run(repo: str, slot: datetime) -> dict | None:
    workflow = "overnight-development.yml"
    data = github_json(
        "https://api.github.com/repos/"
        + quote(repo, safe="/")
        + f"/actions/workflows/{workflow}/runs?event=schedule&per_page=20"
    )
    window_end = slot + timedelta(minutes=120)
    window_start = slot - timedelta(minutes=20)
    for run in data.get("workflow_runs", []):
        if run.get("name") != "Autonomous Development Loop" or run.get("event") != "schedule":
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(JST)
        if window_start <= created <= window_end:
            return run
    return None


def main() -> int:
    now = datetime.now(timezone.utc)
    slot = expected_slot(now)
    repo = os.environ["GITHUB_REPOSITORY"]
    problems: list[str] = []
    run = find_scheduled_run(repo, slot)

    if run is None:
        problems.append(f"scheduled run missing for {slot.isoformat()}")
    else:
        run_id = str(run["id"])
        if run.get("status") not in {"queued", "in_progress"}:
            try:
                client = GoogleSheetsClient()
                records = client.search_column(LEDGER_RANGE, 1, run_id)
                if not records:
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
