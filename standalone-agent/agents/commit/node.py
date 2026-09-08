"""
Phase4b: Commit Agent

条件:
- pytest成功時のみcommitする
- pytest失敗時は何もしない
- deployはまだ行わない
"""

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
        # Keep compatibility with existing tests/mocks that predate the timeout
        # parameter. Real subprocess.run supports timeout, so production keeps
        # the bounded execution guard.
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout=e.stdout or "",
            stderr=(e.stderr or "") + f"\n[TIMEOUT] git command timed out after {GIT_COMMAND_TIMEOUT}s",
        )


def commit_node(state):
    results = dict(state.get("agent_results", {}))
    test_result = state.get("test_result", {})

    if not test_result.get("passed"):
        commit_result = {
            "committed": False,
            "skipped": True,
            "reason": "pytest not passed",
        }
        results["commit"] = commit_result
        return {
            **state,
            "agent_results": results,
            "commit_result": commit_result,
        }

    workdir = os.environ.get("REPO_WORKDIR", os.getcwd())

    add = _run_git(["add", "."], cwd=workdir)
    if add.returncode != 0:
        commit_result = {"committed": False, "error": add.stderr}
        results["commit"] = commit_result
        return {
            **state,
            "agent_results": results,
            "commit_result": commit_result,
        }

    message = (
        state.get("agent_results", {})
        .get("fix", {})
        .get("commit_message", "AI Debug Agent automatic fix")
    )

    commit = _run_git(["commit", "-m", message], cwd=workdir)
    if commit.returncode != 0:
        commit_result = {"committed": False, "error": commit.stderr}
        results["commit"] = commit_result
        return {
            **state,
            "agent_results": results,
            "commit_result": commit_result,
        }

    log = _run_git(["rev-parse", "HEAD"], cwd=workdir)
    commit_result = {
        "committed": True,
        "hash": log.stdout.strip(),
        "message": message,
    }
    results["commit"] = commit_result
    return {
        **state,
        "agent_results": results,
        "commit_result": commit_result,
    }
