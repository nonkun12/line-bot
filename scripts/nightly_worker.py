"""Nightly development worker with one-shot self-healing and loop guards.

Safety contract:
- baseline smoke test runs once;
- pytest runs once;
- only a pytest failure can start the AI repair pipeline;
- the repair pipeline is invoked at most once;
- AUTO_APPLY_PATCH is enabled only inside that one repair invocation;
- Commit Agent may commit only patch-target files and only after pytest passes;
- this workflow must be schedule/dispatch-only so a repair commit cannot invoke
  the worker recursively.

The worker never performs a second repair attempt after an unsuccessful repair.
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
COMMAND_TIMEOUT_SECONDS = 900


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> dict:
    """Run one command exactly once and capture bounded output."""
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        env=env,
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
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("## Nightly Worker\n")
            fh.write(f"- Status: **{summary['status']}**\n")
            fh.write(f"- Next action: `{summary['next_action']}`\n")
            fh.write(f"- Repair attempts: `{summary['repair_attempts']}`\n")


def invoke_one_shot_repair(pytest_output: str) -> dict:
    """Invoke the existing LangGraph Debug→Fix→Patch→Test→Commit route once."""
    script = r'''
import json
import os
import sys
from graph.graph import graph

pytest_output = sys.stdin.read()
state = {
    "user_id": "nightly-worker",
    "request_id": "nightly-worker",
    "raw_message": "debug\n" + pytest_output,
    "agent_results": {},
}

# The worker is the explicit safety boundary: this flag exists only for this
# single graph invocation. The graph itself keeps its existing per-node gates.
os.environ["AUTO_APPLY_PATCH"] = "true"
os.environ["REPO_WORKDIR"] = os.getcwd()

result = graph.invoke(state)
print(json.dumps({
    "final_reply": result.get("final_reply"),
    "patch_result": result.get("patch_result"),
    "test_result": result.get("test_result"),
    "commit_result": result.get("commit_result"),
    "agent_results": result.get("agent_results", {}),
}, ensure_ascii=False, default=str))
'''

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        input=pytest_output,
        text=True,
        capture_output=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        env={**os.environ, "AUTO_APPLY_PATCH": "true", "REPO_WORKDIR": str(ROOT)},
    )

    return {
        "command": "python -c <one-shot LangGraph repair>",
        "returncode": proc.returncode,
        "stdout": proc.stdout[-MAX_OUTPUT_CHARS:],
        "stderr": proc.stderr[-MAX_OUTPUT_CHARS:],
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()

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

    tests = run([sys.executable, "-m", "pytest", "-q"])
    if tests["returncode"] == 0:
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

    # A repair is opt-in. The dedicated nightly workflow sets this explicitly.
    if os.environ.get("NIGHTLY_AUTOFIX", "false").lower() != "true":
        summary = {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "FAIL",
            "stop_reason": "pytest_failed_autofix_disabled",
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

    # Exactly one repair attempt. No retry branch exists by design.
    repair = invoke_one_shot_repair(
        tests["stdout"] + "\n" + tests["stderr"]
    )

    repair_stdout = repair.get("stdout", "")
    repair_ok = False
    try:
        payload = json.loads(repair_stdout.splitlines()[-1])
        test_result = payload.get("test_result") or {}
        commit_result = payload.get("commit_result") or {}
        repair_ok = (
            repair["returncode"] == 0
            and test_result.get("passed") is True
            and commit_result.get("committed") is True
        )
    except (ValueError, IndexError, AttributeError):
        payload = {}

    summary = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if repair_ok else "FAIL",
        "stop_reason": "repair_succeeded" if repair_ok else "repair_failed_no_retry",
        "smoke_test": smoke,
        "pytest": tests,
        "repair": repair,
        "repair_attempts": 1,
        "max_repair_attempts": 1,
        "next_action": "review_commit" if repair_ok else "review_repair_failure",
        "mutation_policy": "one_shot_patch_and_commit" if repair_ok else "stopped_after_one_attempt",
    }
    write_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if repair_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
