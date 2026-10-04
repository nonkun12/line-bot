"""Append one immutable autonomous-development execution record to Google Sheets."""
from __future__ import annotations

from dataclasses import dataclass
import os
import re

from agents.sheets.client import GoogleSheetsClient

LEDGER_RANGE = (
    os.getenv("AUTONOMOUS_DEV_LEDGER_RANGE")
    or os.getenv("GOOGLE_SHEETS_AUDIT_RANGE")
    or "AutonomousDevelopment!A:ZZ"
).strip()

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


def _configured_sheet() -> str:
    if "!" not in LEDGER_RANGE:
        raise RuntimeError(f"Unsupported ledger range: {LEDGER_RANGE!r}")
    sheet = LEDGER_RANGE.split("!", 1)[0].strip()
    if not sheet:
        raise RuntimeError(f"Missing sheet name in ledger range: {LEDGER_RANGE!r}")
    return sheet


def _sheet_scan_range() -> str:
    return f"{_configured_sheet()}!A:ZZ"


def _normalized_row(row: list) -> list[str]:
    values = [str(cell) for cell in row[:len(HEADERS)]]
    return values + [""] * (len(HEADERS) - len(values))


def _headers_exist(client: GoogleSheetsClient) -> bool:
    width = len(HEADERS)
    for row in client.read_rows(_sheet_scan_range()):
        if not isinstance(row, list) or len(row) < width:
            continue
        for start in range(0, len(row) - width + 1):
            if row[start:start + width] == HEADERS:
                return True
    return False


def ensure_headers(client: GoogleSheetsClient) -> str:
    """Require the pre-existing ledger; never create/overwrite a new table implicitly."""
    if not _headers_exist(client):
        raise RuntimeError(
            f"Google Sheets ledger headers not found on {_configured_sheet()!r}; "
            "refusing to create or overwrite a table implicitly"
        )
    return _sheet_scan_range()


def _column_to_number(column: str) -> int:
    value = 0
    for char in column:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def _normalize_sheet_name(sheet: str) -> str:
    sheet = sheet.strip()
    if sheet.startswith("'") and sheet.endswith("'"):
        return sheet[1:-1].replace("''", "'")
    return sheet


def _verify_updated_range(updated_range: object, expected_sheet: str) -> str:
    if not isinstance(updated_range, str) or not updated_range.strip():
        raise RuntimeError("Google Sheets append did not return updatedRange")

    match = re.fullmatch(
        r"(.+)!([A-Z]+)([0-9]+):([A-Z]+)([0-9]+)",
        updated_range.strip(),
    )
    if not match:
        raise RuntimeError(
            f"Google Sheets append returned invalid updatedRange={updated_range!r}"
        )

    sheet, start_col, start_row, end_col, end_row = match.groups()
    if _normalize_sheet_name(sheet) != _normalize_sheet_name(expected_sheet):
        raise RuntimeError(
            f"Google Sheets append wrote to unexpected sheet={sheet!r}; "
            f"expected={expected_sheet!r}"
        )
    if start_row != end_row:
        raise RuntimeError(
            f"Google Sheets append must update exactly one row: {updated_range!r}"
        )
    width = _column_to_number(end_col) - _column_to_number(start_col) + 1
    if width != len(HEADERS):
        raise RuntimeError(
            f"Google Sheets append returned unexpected column width={updated_range!r}"
        )
    return updated_range.strip()


def _existing_matching_run(
    client: GoogleSheetsClient, record: AutonomousRunRecord
) -> bool:
    expected = record.values()
    run_id = str(record.run_id)
    width = len(HEADERS)

    for row in client.read_rows(_sheet_scan_range()):
        if not isinstance(row, list) or run_id not in {str(cell) for cell in row}:
            continue

        for start in range(0, max(1, len(row) - width + 1)):
            if _normalized_row(row[start:start + width]) == expected:
                return True

        raise RuntimeError(
            "Google Sheets contains an existing run_id with mismatched ledger data: "
            f"{record.run_id}"
        )

    return False


def append_once(client: GoogleSheetsClient, record: AutonomousRunRecord) -> bool:
    """Append once to the existing sheet table and verify the actual returned row."""
    try:
        target_range = ensure_headers(client)
    except Exception as exc:
        raise RuntimeError(
            f"Google Sheets ledger header/read failed for sheet={_configured_sheet()!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        if _existing_matching_run(client, record):
            return False
    except Exception as exc:
        raise RuntimeError(
            f"Google Sheets duplicate-check failed for run_id={record.run_id}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        response = client.append_row(target_range, record.values())
    except Exception as exc:
        raise RuntimeError(
            f"Google Sheets append API failed for run_id={record.run_id}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    updates = response.get("updates", {}) if isinstance(response, dict) else {}
    if updates.get("updatedRows") != 1:
        raise RuntimeError(
            f"Google Sheets append updatedRows={updates.get('updatedRows')!r}"
        )

    try:
        readback_range = _verify_updated_range(
            updates.get("updatedRange"), _configured_sheet()
        )
        rows = client.read_rows(readback_range)
    except Exception as exc:
        raise RuntimeError(
            f"Google Sheets append verification failed for run_id={record.run_id}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if len(rows) != 1 or _normalized_row(rows[0]) != record.values():
        raise RuntimeError(
            f"Google Sheets append read-back mismatch for run_id={record.run_id}"
        )
    return True


def build_record_from_env() -> AutonomousRunRecord:
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
    """Record the run, retrying the Google API once after an exception."""
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
        "Google Sheets autonomous ledger write failed after bounded retry: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error
