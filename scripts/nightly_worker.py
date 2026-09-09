"""Nightly autonomous-development coordinator.

This coordinator is intentionally conservative: it never edits source code itself.
It validates the repository, runs the existing safe nightly smoke test and pytest,
and emits a machine-readable run summary for the follow-up agents/workflows.
Future implementation agents can consume the summary without granting this job
permission to modify production source automatically.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "nightly_worker_summary.json"


def run(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=900)
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    smoke = run([sys.executable, "scripts/nightly_development_test.py"])
    tests = run([sys.executable, "-m", "pytest", "-q"])
    status = "PASS" if smoke["returncode"] == 0 and tests["returncode"] == 0 else "FAIL"

    summary = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "smoke_test": smoke,
        "pytest": tests,
        "next_action": "review_failure" if status == "FAIL" else "ready_for_ai_task_review",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
