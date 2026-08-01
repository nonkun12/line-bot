"""
Phase4b: Commit Agent

条件:
- pytest成功時のみcommitする
- pytest失敗時は何もしない
- deployはまだ行わない
"""

import os
import subprocess


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def commit_node(state):

    results = dict(
        state.get("agent_results", {})
    )

    test_result = state.get(
        "test_result",
        {}
    )

    # pytest成功確認
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


    workdir = os.environ.get(
        "REPO_WORKDIR",
        os.getcwd()
    )


    # git add
    add = _run_git(
        ["add", "."],
        cwd=workdir,
    )


    if add.returncode != 0:
        commit_result = {
            "committed": False,
            "error": add.stderr,
        }

        results["commit"] = commit_result

        return {
            **state,
            "agent_results": results,
            "commit_result": commit_result,
        }


    # commit message
    message = (
        state
        .get("agent_results", {})
        .get("fix", {})
        .get(
            "commit_message",
            "AI Debug Agent automatic fix"
        )
    )


    commit = _run_git(
        [
            "commit",
            "-m",
            message,
        ],
        cwd=workdir,
    )


    if commit.returncode != 0:
        commit_result = {
            "committed": False,
            "error": commit.stderr,
        }

        results["commit"] = commit_result

        return {
            **state,
            "agent_results": results,
            "commit_result": commit_result,
        }


    log = _run_git(
        [
            "rev-parse",
            "HEAD",
        ],
        cwd=workdir,
    )


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
