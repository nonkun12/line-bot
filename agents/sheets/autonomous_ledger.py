"""Append one immutable autonomous-development execution record to Google Sheets.

This module is intentionally separate from user-facing Sheets operations.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

from agents.sheets.client import GoogleSheetsClient


LEDGER_RANGE = os.getenv("AUTONOMOUS_DEV_LEDGER_RANGE", "AutonomousDevelopment!A:L")
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


def append_once(client: GoogleSheetsClient, record: AutonomousRunRecord) -> bool:
    """Write exactly once for run_id; retries are idempotent."""
    existing = client.search(LEDGER_RANGE, record.run_id)
    if any(record.run_id in [str(cell) for cell in row] for row in existing):
        return False
    client.append_row(LEDGER_RANGE, record.values())
    return True


def build_record_from_env() -> AutonomousRunRecord:
    return AutonomousRunRecord(
        timestamp=os.getenv("AUTONOMOUS_TIMESTAMP", ""),
        run_id=os.environ["GITHUB_RUN_ID"],
        task_id=os.getenv("AUTONOMOUS_TASK_ID", "autonomous-development"),
        source=os.getenv("AUTONOMOUS_SOURCE", "scheduler"),
        agent=os.getenv("AUTONOMOUS_AGENT", "ManagementAI"),
        task_summary=os.getenv("DEV_INSTRUCTION", ""),
        base_sha=os.getenv("AUTONOMOUS_START_SHA", ""),
        produced_sha=os.getenv("AUTONOMOUS_PRODUCED_SHA", ""),
        changed_files=os.getenv("AUTONOMOUS_CHANGED_FILES", ""),
        pr_url=os.getenv("AUTONOMOUS_PR_URL", ""),
        tests_result=os.getenv("AUTONOMOUS_TESTS_RESULT", ""),
        verification_result=os.getenv("AUTONOMOUS_VERIFICATION_RESULT", ""),
        safety_gate_result=os.getenv("AUTONOMOUS_SAFETY_GATE_RESULT", ""),
        merge_result=os.getenv("AUTONOMOUS_MERGE_RESULT", "NOT_AUTO_MERGED"),
        blocked_failed_reason=os.getenv("AUTONOMOUS_BLOCKED_FAILED_REASON", ""),
        next_action=os.getenv("AUTONOMOUS_NEXT_ACTION", "review_pr"),
    )


def record_autonomous_run() -> bool:
    client = GoogleSheetsClient()
    return append_once(client, build_record_from_env())
