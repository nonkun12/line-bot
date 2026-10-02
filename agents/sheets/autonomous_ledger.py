"""Append one immutable autonomous-development execution record to Google Sheets.

This module is intentionally separate from user-facing Sheets operations.
It is the canonical ledger used by the nightly autonomous workflow; the optional
`core.line_development_runtime` audit hook is a separate, best-effort path.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re

from agents.sheets.client import GoogleSheetsClient

LEDGER_RANGE = (os.getenv("AUTONOMOUS_DEV_LEDGER_RANGE") or os.getenv("GOOGLE_SHEETS_AUDIT_RANGE") or "AutonomousDevelopment!A:Q").strip()
HEADERS = [
    "timestamp", "run_id", "task_id", "source", "agent", "task_summary",
    "base_sha", "produced_sha", "changed_files", "pr_url", "tests_result",
    "verification_result", "safety_gate_result", "merge_result",
    "blocked_failed_reason", "next_action", "logging_result",
]


@dataclass(frozen=True)
class AutonomousRunRecord:
    timestamp: str
    run_id: str
    task_id: str
    source: str
    agent: str
    task_summary: str
    base_sha: str
    produced_sha: str
    changed_files: str
    pr_url: str
    tests_result: str
    verification_result: str
    safety_gate_result: str
    merge_result: str
    blocked_failed_reason: str
    next_action: str
    logging_result: str = "RECORDED"

    def values(self) -> list[str]:
        return [getattr(self, field) for field in (
            "timestamp", "run_id", "task_id", "source", "agent",
            "task_summary", "base_sha", "produced_sha", "changed_files",
            "pr_url", "tests_result", "verification_result",
            "safety_gate_result", "merge_result", "blocked_failed_reason",
            "next_action", "logging_result",
        )]


def ensure_headers(client: GoogleSheetsClient) -> None:
    sheet = LEDGER_RANGE.split("!", 1)[0]
    header_range = f"{sheet}!A1:Q1"
    existing = client.read_rows(header_range)
    if not existing:
        client.update_row(header_range, HEADERS)
        return
    if existing[0] != HEADERS:
        raise RuntimeError(f"Google Sheets ledger header mismatch in {header_range}")


def _normalized_row(row: list) -> list[str]:
    """Normalize Sheets' trimmed trailing cells to the fixed ledger width."""
    values = [str(cell) for cell in row[:len(HEADERS)]]
    return values + [""] * (len(HEADERS) - len(values))


def _normalized_slice(row: list, start: int) -> list[str]:
    values = [str(cell) for cell in row[start : start + len(HEADERS)]]
    return values + [""] * (len(HEADERS) - len(values))


def _column_number(label: str) -> int:
    number = 0
    for char in label:
        number = number * 26 + (ord(char) - ord("A") + 1)
    return number


def _verify_updated_range(updated_range: object) -> str:
    if not isinstance(updated_range, str) or not updated_range.strip():
        raise RuntimeError("Google Sheets append did not return updatedRange")

    match = re.fullmatch(r"(.+)!([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)", updated_range.strip())
    if not match:
        raise RuntimeError(f"Google Sheets append returned invalid updatedRange={updated_range!r}")

    sheet, start_col, start_row, end_col, end_row = match.groups()
    expected_sheet = LEDGER_RANGE.split("!", 1)[0].strip()
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    if expected_sheet.startswith("'") and expected_sheet.endswith("'"):
        expected_sheet = expected_sheet[1:-1].replace("''", "'")
    if sheet != expected_sheet:
        raise RuntimeError(
            f"Google Sheets append wrote to unexpected sheet={sheet!r}; expected={expected_sheet!r}"
        )

    width = _column_number(end_col) - _column_number(start_col) + 1
    if width != len(HEADERS) or start_row != end_row:
        raise RuntimeError(f"Google Sheets append returned unexpected row range={updated_range!r}")

    return f"{sheet}!{start_col}{start_row}:{end_col}{end_row}"


def _find_existing_run(client: GoogleSheetsClient, sheet: str, record: AutonomousRunRecord) -> bool:
    """Find an existing run_id and verify its complete 17-cell ledger row.

    Prefer the canonical A:Q lookup for compatibility with existing clients,
    then scan the used area because Sheets can append to its detected table
    range (for example K:AA) even when A:Q was requested.
    """
    expected = record.values()
    canonical = client.search_column(f"{sheet}!A:Q", 1, record.run_id)
    if canonical:
        for row in canonical:
            if _normalized_row(row) == expected:
                return True
        raise RuntimeError(
            f"Google Sheets contains an existing run_id with mismatched ledger data: {record.run_id}"
        )

    rows = client.read_rows(f"{sheet}!A:ZZ")
    for row in rows:
        for index, cell in enumerate(row):
            if str(cell) != record.run_id or index == 0:
                continue
            start = index - 1
            if _normalized_slice(row, start) == expected:
                return True
            raise RuntimeError(
                f"Google Sheets contains an existing run_id with mismatched ledger data: {record.run_id}"
            )
    return False


def append_once(client: GoogleSheetsClient, record: AutonomousRunRecord) -> bool:
    """Write once per exact run_id and verify the actual row after the append.

    A matching existing run_id is idempotent only when its full row matches the
    same record. A stale or conflicting row fails closed instead of being trusted.
    """
    ensure_headers(client)
    sheet = LEDGER_RANGE.split("!", 1)[0]
    expected = record.values()
    if _find_existing_run(client, sheet, record):
        return False

    response = client.append_row(LEDGER_RANGE, expected)
    updates = response.get("updates", {}) if isinstance(response, dict) else {}
    if updates.get("updatedRows") != 1:
        raise RuntimeError(f"Google Sheets append updatedRows={updates.get('updatedRows')!r}")

    readback_range = _verify_updated_range(updates.get("updatedRange"))
    rows = client.read_rows(readback_range)
    if len(rows) != 1 or _normalized_row(rows[0]) != expected:
        raise RuntimeError(
            f"Google Sheets append read-back mismatch for run_id={record.run_id}"
        )
    return True


def build_record_from_env() -> AutonomousRunRecord:
    """Build an audit row that states whether Hermes actually participated."""
    task_summary = os.getenv("DEV_INSTRUCTION", "")
    hermes_invoked = os.getenv("HERMES_ADVISOR_INVOKED", "false").strip().lower() == "true"
    hermes_used = os.getenv("HERMES_ADVISOR_USED", "false").strip().lower() == "true"
    hermes_reason = os.getenv("HERMES_ADVISOR_REASON", "").strip()
    if hermes_invoked:
        action = "Hermes advisor invoked"
        if hermes_used:
            action += "; advisory appended to development instruction"
        elif hermes_reason:
            action += f"; not used: {hermes_reason}"
        task_summary = f"{task_summary} [{action}]"
    else:
        task_summary = f"{task_summary} [Hermes advisor not invoked]"
    agent = os.getenv("AUTONOMOUS_AGENT", "ManagementAI")
    if hermes_invoked:
        agent = f"{agent}+HermesAdvisor"
    return AutonomousRunRecord(
        timestamp=os.getenv("AUTONOMOUS_TIMESTAMP", ""),
        run_id=os.environ["GITHUB_RUN_ID"],
        task_id=os.getenv("AUTONOMOUS_TASK_ID", "autonomous-development"),
        source=os.getenv("AUTONOMOUS_SOURCE", "scheduler"),
        agent=agent,
        task_summary=task_summary[:4000],
        base_sha=os.getenv("AUTONOMOUS_START_SHA", ""),
        produced_sha=os.getenv("AUTONOMOUS_PRODUCED_SHA", ""),
        changed_files=os.getenv("AUTONOMOUS_CHANGED_FILES", ""),
        pr_url=os.getenv("AUTONOMOUS_PR_URL", ""),
        tests_result=os.getenv("AUTONOMOUS_TESTS_RESULT", ""),
        verification_result=os.getenv("AUTONOMOUS_VERIFICATION_RESULT", "NOT_RUN"),
        safety_gate_result=os.getenv("AUTONOMOUS_SAFETY_GATE_RESULT", "BLOCKED"),
        merge_result=os.getenv("AUTONOMOUS_MERGE_RESULT", "NOT_AUTO_MERGED"),
        blocked_failed_reason=os.getenv("AUTONOMOUS_BLOCKED_FAILED_REASON", ""),
        next_action=os.getenv("AUTONOMOUS_NEXT_ACTION", "review_pr"),
    )


def record_autonomous_run() -> bool:
    """Record the run, retrying transient Google API failures once."""
    last_error: Exception | None = None
    record = build_record_from_env()
    for attempt in range(2):
        try:
            return append_once(GoogleSheetsClient(), record)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                continue
    assert last_error is not None
    raise RuntimeError(
        f"Google Sheets autonomous ledger write failed after bounded retry: {last_error}"
    ) from last_error
