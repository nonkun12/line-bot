"""
Phase4b: Commit Agent

条件:
- pytest成功時のみcommitする
- pytest失敗時は何もしない
- Patch Agentが対象としたファイルだけをcommitする
- deployはまだ行わない
"""

import os
import subprocess
from pathlib import PurePosixPath


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _candidate_paths(state) -> list[str]:
    """Patch候補から安全な相対ファイルパスだけを取得する。"""
    candidates = state.get("patch_candidates", []) or []
    paths = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw = candidate.get("target_file")
        if not isinstance(raw, str) or not raw.strip():
            continue

        path = raw.strip().replace("\\", "/")
        pure = PurePosixPath(path)

        # リポジトリ外を指すパスや絶対パスは拒否する。
        if pure.is_absolute() or ".." in pure.parts or path == ".":
            continue

        paths.append(path)

    return list(dict.fromkeys(paths))


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
    paths = _candidate_paths(state)

    if not paths:
        commit_result = {
            "committed": False,
            "skipped": True,
            "reason": "no safe patch target files",
        }
        results["commit"] = commit_result
        return {
            **state,
            "agent_results": results,
            "commit_result": commit_result,
        }

    # Patch Agentが変更対象として特定したファイルだけをstageする。
    # 以前の `git add .` は無関係な既存変更までcommitする危険があった。
    add = _run_git(["add", "--", *paths], cwd=workdir)

    if add.returncode != 0:
        commit_result = {
            "committed": False,
            "error": add.stderr,
            "paths": paths,
        }
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
        commit_result = {
            "committed": False,
            "error": commit.stderr,
            "paths": paths,
        }
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
        "paths": paths,
    }

    results["commit"] = commit_result

    return {
        **state,
        "agent_results": results,
        "commit_result": commit_result,
    }
