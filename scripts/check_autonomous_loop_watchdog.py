"""Verify that each distributed-loop schedule slot executed a verified task and was audited."""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

from agents.sheets.autonomous_ledger import (
    HEADERS,
    _resolved_sheet,
    _sheet_scan_range,
)
from agents.sheets.client import GoogleSheetsClient

JST = ZoneInfo("Asia/Tokyo")
SLOT_MINUTE = 17
SLOT_CHECK_DELAY_MINUTES = 115
SLOT_DISCOVERY_WINDOW_MINUTES = 55
MAX_RUN_RUNTIME_MINUTES = 40
INVALID_TASK_IDS = {"", "NOT_RUN", "QUEUE_EMPTY", "QUEUE_EXHAUSTED_NO_TASKS"}


def github_json(url: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


class _StripAuthorizationRedirectHandler(HTTPRedirectHandler):
    """Never forward GitHub credentials to an artifact storage redirect host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Artifact download URLs are signed and do not need the API bearer token.
        return Request(
            newurl,
            headers={"Accept": "application/vnd.github+json"},
            origin_req_host=req.origin_req_host,
            unverifiable=True,
        )


def github_bytes(url: str) -> bytes:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    req = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    opener = build_opener(_StripAuthorizationRedirectHandler())
    with opener.open(req, timeout=30) as response:
        return response.read()


def load_previous_audit_cursor(repo: str) -> datetime | None:
    """Recover the last completed audit cursor from the previous run artifact."""
    current_run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    workflow = "autonomous-development-watchdog.yml"
    data = github_json(
        "https://api.github.com/repos/" + quote(repo, safe="/")
        + f"/actions/workflows/{workflow}/runs?per_page=100"
    )
    for run in data.get("workflow_runs", []):
        run_id = str(run.get("id", ""))
        if not run_id or run_id == current_run_id or run.get("status") != "completed":
            continue
        artifacts = github_json(
            "https://api.github.com/repos/" + quote(repo, safe="/")
            + f"/actions/runs/{run_id}/artifacts?per_page=100"
        )
        artifact = next((item for item in artifacts.get("artifacts", [])
                         if item.get("name") == f"autonomous-watchdog-{run_id}"
                         and item.get("expired") is not True), None)
        if artifact is None:
            continue
        archive = github_bytes(artifact["archive_download_url"])
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            candidates = [name for name in bundle.namelist() if name.endswith("watchdog_result.json")]
            if len(candidates) != 1:
                continue
            payload = json.loads(bundle.read(candidates[0]).decode("utf-8"))
        raw_cursor = payload.get("audited_through")
        if isinstance(raw_cursor, str) and raw_cursor:
            parsed = datetime.fromisoformat(raw_cursor)
            if parsed.tzinfo is None:
                raise RuntimeError("previous watchdog cursor is missing timezone")
            return parsed.astimezone(JST)
    return None


def expected_slot(now: datetime) -> datetime:
    """Select the latest hourly loop slot old enough for its bounded run window."""
    local = now.astimezone(JST).replace(second=0, microsecond=0)
    cutoff = local - timedelta(minutes=SLOT_CHECK_DELAY_MINUTES)
    candidate = local.replace(minute=SLOT_MINUTE)
    while candidate > cutoff:
        candidate -= timedelta(hours=1)
    return candidate


def find_scheduled_run(repo: str, slot: datetime) -> dict | None:
    workflow = "distributed-autonomous-loop.yml"
    data = github_json(
        "https://api.github.com/repos/"
        + quote(repo, safe="/")
        + f"/actions/workflows/{workflow}/runs?event=schedule&per_page=100"
    )
    # Keep the scheduler discovery window below the hourly slot interval
    # while allowing up to 55 minutes of scheduler delay.
    window_end = slot + timedelta(minutes=SLOT_DISCOVERY_WINDOW_MINUTES)
    window_start = slot - timedelta(minutes=10)
    for run in data.get("workflow_runs", []):
        # The workflow uses run-name, so the API name field may contain
        # a title such as "Distributed Loop (continuation_depth=0)" rather than
        # the workflow name. The endpoint is already scoped to this workflow;
        # filter by event only and rely on the bounded timestamp window.
        if run.get("event") != "schedule":
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



def run_is_pending_within_grace(run: dict | None, slot: datetime, now: datetime) -> bool:
    """Keep delayed schedule publication and bounded queue waits from looking like failures."""
    elapsed = now.astimezone(JST) - slot.astimezone(JST)
    if elapsed < timedelta(0):
        return False

    if run is None:
        # Wait only through the same non-overlapping scheduler discovery window.
        return elapsed <= timedelta(minutes=SLOT_DISCOVERY_WINDOW_MINUTES)

    status = run.get("status")
    if status == "queued":
        # A queued hourly run must not remain pending beyond its audit deadline.
        return elapsed < timedelta(minutes=SLOT_CHECK_DELAY_MINUTES)

    if status != "in_progress":
        return False

    started_at = run.get("run_started_at")
    if isinstance(started_at, str) and started_at:
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            started = None
        if started is not None:
            running_for = now.astimezone(JST) - started.astimezone(JST)
            return timedelta(0) <= running_for < timedelta(minutes=MAX_RUN_RUNTIME_MINUTES)

    # Older API/test fixtures may not provide run_started_at. Keep a bounded
    # fallback tied to the expected hourly slot.
    return elapsed < timedelta(minutes=SLOT_CHECK_DELAY_MINUTES)

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


def _audit_slot(repo: str, slot: datetime, now: datetime) -> dict:
    problems: list[str] = []
    run = find_scheduled_run(repo, slot)
    pending = False
    if run is None:
        pending = run_is_pending_within_grace(None, slot, now)
        if not pending:
            problems.append(f"distributed scheduled run missing after grace for {slot.isoformat()}")
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
    return {
        "slot": slot.isoformat(), "pending": pending,
        "run_id": str(run["id"]) if run else None,
        "run_status": run.get("status") if run else None,
        "run_conclusion": run.get("conclusion") if run else None,
        "problems": problems,
    }


def main() -> int:
    now = datetime.now(timezone.utc)
    latest_slot = expected_slot(now)
    repo = os.environ["GITHUB_REPOSITORY"]
    cursor = load_previous_audit_cursor(repo)
    cursor_initialized = cursor is None
    if cursor is None:
        # Bootstrap the first deployment with a bounded 24-slot backfill.
        cursor = latest_slot - timedelta(hours=24)

    audited: list[dict] = []
    problems: list[str] = []
    pending = False
    audited_through = cursor
    slot = cursor + timedelta(hours=1)
    # Bounded catch-up: older unprocessed slots are handled first on the next run.
    while slot <= latest_slot and len(audited) < 24:
        try:
            item = _audit_slot(repo, slot, now)
        except Exception as exc:
            problems.append(f"audit failed for {slot.isoformat()}: {type(exc).__name__}: {exc}")
            break
        audited.append(item)
        if item["pending"]:
            pending = True
            break
        problems.extend(item["problems"])
        audited_through = slot
        slot += timedelta(hours=1)

    backlog_remaining = audited_through < latest_slot and not pending
    result = {
        "ok": not problems,
        "pending": pending,
        "cursor_initialized": cursor_initialized,
        "audited_slots": audited,
        "audited_count": len(audited),
        "audited_through": audited_through.isoformat(),
        "latest_expected_slot": latest_slot.isoformat(),
        "backlog_remaining": backlog_remaining,
        "problems": problems,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
