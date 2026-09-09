"""Nightly development coordinator with hard anti-loop safety gates.

This coordinator is intentionally conservative. It does not edit source files,
commit, push, or deploy. It performs exactly one baseline smoke test followed
by at most one pytest run. A smoke-test failure stops the run immediately, and
a pytest failure is reported as a single actionable failure for the Debug/Fix
pipeline rather than retried in a loop.

The autonomous repair pipeline must be invoked by a separate, explicitly
configured workflow. Keeping diagnosis/execution separate prevents a broken
nightly run from recursively triggering itself.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "nightly_worker_summary.json"
MAX_OUTPUT_CHARS = 12000
PYTEST_TIMEOUT_SECONDS = 900


def run(cmd: list[str]) -> dict:
    """Run one command exactly once and capture bounded output."""
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=PYTEST_TIMEOUT_SECONDS,
    )
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-MAX_OUTPUT_CHARS:],
        "stderr": proc.stderr[-MAX_OUTPUT_CHARS:],
    }


def write_summary(summary: dict) -> None:
    SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        status = summary["status"]
        next_action = summary["next_action"]
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("## Nightly Worker\n")
            fh.write(f"- Status: **{status}**\n")
            fh.write(f"- Next action: `{next_action}`\n")
            fh.write(f"- Repair attempts: `{summary['repair_attempts']}`\n")


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()

    # Hard gate 1: repository/smoke validation. Never continue after failure.
    smoke = run([sys.executable, "scripts/nightly_development_test.py"])
    if smoke["returncode"] != 0:
        summary = {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "FAIL",
            "stop_reason": "baseline_smoke_failed",
            "smoke_test": smoke,
            "pytest": None,
            "repair_attempts": 0,
            "max_repair_attempts": 1,
            "next_action": "review_smoke_failure",
            "mutation_policy": "read_only",
        }
        write_summary(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    # Hard gate 2: one and only one full pytest attempt.
    tests = run([sys.executable, "-m", "pytest", "-q"])
    if tests["returncode"] != 0:
        summary = {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "FAIL",
            "stop_reason": "pytest_failed_no_retry",
            "smoke_test": smoke,
            "pytest": tests,
            "repair_attempts": 0,
            "max_repair_attempts": 1,
            "next_action": "send_once_to_debug_fix_pipeline",
            "mutation_policy": "read_only",
        }
        write_summary(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    summary = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "stop_reason": "no_failure",
        "smoke_test": smoke,
        "pytest": tests,
        "repair_attempts": 0,
        "max_repair_attempts": 1,
        "next_action": "ready_for_ai_task_review",
        "mutation_policy": "read_only",
    }
    write_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
