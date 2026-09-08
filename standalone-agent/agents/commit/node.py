"""Commit Agent for isolated overnight development workspaces."""

from __future__ import annotations

import os
import subprocess

GIT_COMMAND_TIMEOUT = float(os.environ.get("GIT_COMMAND_TIMEOUT", "10.0"))


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    command = ["git"] + args
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT,
        )
    except TypeError:
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout=e.stdout or "",
            stderr=(e.stderr or "") + f"\n[TIMEOUT] git command timed out after {GIT_COMMAND_TIMEOUT}s",
        )


def _ensure_job_branch(workdir: str, job_id) -> str | None:
    if job_id is None:
        return None
    branch_name = f"worker/job-{job_id}"
    current = _run_git(["branch", "--show-current"], cwd=workdir)
    if current.returncode == 0 and current.stdout.strip() == branch_name:
        return branch_name

    exists = _run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=workdir,
    )
    if exists.returncode == 0:
        switch = _run_git(["switch", branch_name], cwd=workdir)
    else:
        switch = _run_git(["switch", "-c", branch_name], cwd=workdir)

    if switch.returncode != 0:
        raise RuntimeError(switch.stderr.strip() or "failed to select job branch")
    return branch_name


def commit_node(state):
    results = dict(state.get("agent_results", {}))
    test_result = state.get("test_result", {})

    if not test_result.get("passed"):
        commit_result = {"committed": False, "skipped": True, "reason": "pytest not passed"}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    workdir = state.get("workdir") or os.environ.get("REPO_WORKDIR") or os.getcwd()
    job_id = state.get("job_id")
    try:
        branch = _ensure_job_branch(workdir, job_id)
    except RuntimeError as exc:
        commit_result = {"committed": False, "error": str(exc)}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    add = _run_git(["add", "."], cwd=workdir)
    if add.returncode != 0:
        commit_result = {"committed": False, "error": add.stderr}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    message = state.get("agent_results", {}).get("fix", {}).get(
        "commit_message", "AI Debug Agent automatic fix"
    )
    commit = _run_git(["commit", "-m", message], cwd=workdir)
    if commit.returncode != 0:
        commit_result = {"committed": False, "error": commit.stderr}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    log = _run_git(["rev-parse", "HEAD"], cwd=workdir)
    commit_result = {
        "committed": True,
        "hash": log.stdout.strip(),
        "message": message,
        "branch": branch,
    }
    results["commit"] = commit_result
    return {**state, "agent_results": results, "commit_result": commit_result}
