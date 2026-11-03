"""Workflow-side adapter for executing one persisted Goal child through the guarded runtime.

This module is intentionally not imported by the LINE request handler. It is
meant to be called only from an authenticated, isolated GitHub Actions worker.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from typing import Any

from core import line_development_runtime
import goal_job_worker


def _git(*args: str) -> str:
    completed = subprocess.run(
        ("git", *args), capture_output=True, text=True, timeout=20, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {completed.stderr[-1000:]}")
    return completed.stdout.strip()


def execute_goal_child(
    job: dict[str, Any],
    payload: dict[str, Any],
    *,
    runtime_execute: Callable[..., int] | None = None,
    git: Callable[..., str] = _git,
) -> dict[str, Any]:
    """Execute one already-authorized Goal child and return bounded provenance.

    The caller must first use goal_job_store.authorize_claimed_job via the
    typed worker. This adapter still validates its input and independently
    checks the resulting commit's changed paths against the exact grant.
    """
    if not isinstance(job, dict) or job.get("job_type") != "goal_child":
        raise PermissionError("only typed Goal child jobs may use this adapter")
    if not isinstance(payload, dict):
        raise ValueError("Goal child payload is malformed")
    instruction = payload.get("instruction")
    allowed_paths = payload.get("allowed_paths")
    if (
        not isinstance(instruction, str) or not instruction.strip()
        or not isinstance(allowed_paths, list) or not allowed_paths
        or any(not isinstance(path, str) or not path for path in allowed_paths)
    ):
        raise ValueError("Goal child instruction or exact allowed paths are invalid")
    if len(allowed_paths) != len(set(allowed_paths)):
        raise ValueError("Goal child allowed paths must be unique")

    base_sha = git("rev-parse", "HEAD")
    if not base_sha:
        raise RuntimeError("cannot capture Goal child base SHA")
    execute = runtime_execute or line_development_runtime.execute
    env_keys = ("AUTONOMOUS_TASK_ID", "AUTONOMOUS_RUN_SOURCE")
    previous_env = {key: os.environ.get(key) for key in env_keys}
    os.environ["AUTONOMOUS_TASK_ID"] = str(payload.get("goal_job_key") or job.get("id"))[:100]
    os.environ["AUTONOMOUS_RUN_SOURCE"] = "goal-child"
    try:
        exit_code = execute(instruction, allowed_paths=allowed_paths)
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    produced_sha = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    changed_raw = git("diff", "--name-only", f"{base_sha}..{produced_sha}") if produced_sha != base_sha else ""
    changed_paths = sorted(path for path in changed_raw.splitlines() if path)
    outside_scope = sorted(set(changed_paths) - set(allowed_paths))
    runtime_passed = exit_code == 0
    scope_passed = not outside_scope
    sha_passed = bool(produced_sha) and produced_sha != base_sha
    checks = [
        {
            "name": "guarded_runtime",
            "status": "PASS" if runtime_passed else "FAIL",
            "source": "core.line_development_runtime.execute",
        },
        {
            "name": "changed_paths_within_goal_grant",
            "status": "PASS" if scope_passed else "FAIL",
            "source": "git diff --name-only base..produced",
        },
        {
            "name": "produced_commit_recorded",
            "status": "PASS" if sha_passed else "FAIL",
            "source": "git rev-parse HEAD",
        },
    ]
    result = {
        "goal_job_id": payload.get("goal_job_key"),
        "exit_code": exit_code,
        "base_sha": base_sha,
        "produced_sha": produced_sha,
        "branch": branch,
        "changed_paths": changed_paths,
        "outside_scope_paths": outside_scope,
    }
    return {"result": json.dumps(result, ensure_ascii=False, sort_keys=True), "evidence": {"checks": checks, **result}}


def run_goal_child_once(*, job_id: int | None = None):
    """Claim one persisted Goal child and execute it through the guarded runtime."""
    return goal_job_worker.run_once(execute_goal_child, job_id=job_id)


__all__ = ["execute_goal_child", "run_goal_child_once"]
