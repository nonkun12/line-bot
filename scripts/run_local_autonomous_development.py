"""Launch one guarded autonomous development cycle from a local Mac.

The launcher intentionally reuses core.line_development_runtime so local
development gets the same worktree safety, tests, rollback, and audit logging
as the hosted autonomous worker.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTRUCTION = (
    "Perform one bounded autonomous development cycle. "
    "Improve the existing Control Tower, AIGateway, AgentRegistry, "
    "Supervisor, or Router foundations only when a safe, test-backed "
    "improvement is identified. Preserve existing behavior and safety gates."
)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def main() -> int:
    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    if status.returncode != 0:
        print(status.stderr[-3000:], flush=True)
        return 1
    if status.stdout.strip():
        print("LOCAL_AUTONOMOUS_DEV=BLOCKED: worktree is not clean", flush=True)
        print(status.stdout[-3000:], flush=True)
        return 1

    if not os.environ.get("GROQ_API_KEY"):
        print("LOCAL_AUTONOMOUS_DEV=BLOCKED: GROQ_API_KEY is not set", flush=True)
        return 1

    run_id = datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%SZ")
    env = os.environ.copy()
    env["GITHUB_RUN_ID"] = run_id
    env["AUTONOMOUS_RUN_SOURCE"] = "mac-local"
    env["DEV_INSTRUCTION"] = os.environ.get(
        "DEV_INSTRUCTION", DEFAULT_INSTRUCTION
    )[:8000]

    print(f"LOCAL_AUTONOMOUS_DEV=START run_id={run_id}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "core.line_development_runtime"],
        cwd=ROOT,
        env=env,
        text=True,
    )
    print(
        f"LOCAL_AUTONOMOUS_DEV={'PASS' if result.returncode == 0 else 'FAIL'} "
        f"run_id={run_id}",
        flush=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
