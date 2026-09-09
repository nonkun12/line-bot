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


def _run_git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _candidate_paths(state, workdir: str | None = None) -> list[str]:
    """Patch候補から安全なリポジトリ内の相対ファイルパスだけを取得する。"""
    candidates = state.get("patch_candidates", []) or []
    paths = []
    root = os.path.realpath(workdir or os.getcwd())

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw = candidate.get("target_file")
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            continue

        path = raw.strip().replace("\\", "/")
        pure = PurePosixPath(path)

        if (
            pure.is_absolute()
            or ".." in pure.parts
            or path == "."
            or (len(path) >= 2 and path[1] == ":")
        ):
            continue

        resolved = os.path.realpath(os.path.join(root, *pure.parts))
        try:
            inside_repo = os.path.commonpath([root, resolved]) == root
        except ValueError:
            inside_repo = False
        if not inside_repo or not os.path.isfile(resolved):
            continue

        normalized = str(pure)
        if normalized not in ("", "."):
            paths.append(normalized)

    return list(dict.fromkeys(paths))


def commit_node(state):
    results = dict(state.get("agent_results", {}))
    test_result = state.get("test_result", {})

    if test_result.get("passed") is not True:
        commit_result = {
            "committed": False,
            "skipped": True,
            "reason": "pytest not passed",
        }
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    workdir = os.environ.get("REPO_WORKDIR", os.getcwd())
    paths = _candidate_paths(state, workdir)

    if not paths:
        commit_result = {"committed": False, "skipped": True, "reason": "no safe patch target files"}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    before_head = _run_git(["rev-parse", "HEAD"], cwd=workdir)
    if before_head.returncode != 0 or not before_head.stdout.strip():
        commit_result = {"committed": False, "error": before_head.stderr or "failed to resolve HEAD before commit", "paths": paths}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}
    before_sha = before_head.stdout.strip()

    add = _run_git(["add", "--", *paths], cwd=workdir)
    if add.returncode != 0:
        commit_result = {"committed": False, "error": add.stderr, "paths": paths}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    staged = _run_git(["diff", "--cached", "--name-only"], cwd=workdir)
    if staged.returncode != 0:
        commit_result = {"committed": False, "error": staged.stderr, "paths": paths}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    staged_paths = {line.strip().replace("\\", "/") for line in staged.stdout.splitlines() if line.strip()}
    if staged_paths != set(paths):
        commit_result = {
            "committed": False,
            "skipped": True,
            "reason": "staged paths differ from safe patch targets",
            "paths": paths,
            "staged_paths": sorted(staged_paths),
        }
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    message = state.get("agent_results", {}).get("fix", {}).get("commit_message", "AI Debug Agent automatic fix")
    commit = _run_git(["commit", "-m", message], cwd=workdir)
    if commit.returncode != 0:
        commit_result = {"committed": False, "error": commit.stderr, "paths": paths}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    log = _run_git(["rev-parse", "HEAD"], cwd=workdir)
    if log.returncode != 0 or not log.stdout.strip():
        commit_result = {"committed": False, "error": log.stderr or "failed to resolve HEAD after commit", "paths": paths}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    after_sha = log.stdout.strip()
    if after_sha == before_sha:
        commit_result = {"committed": False, "error": "HEAD did not advance after commit", "paths": paths, "before_head": before_sha, "after_head": after_sha}
        results["commit"] = commit_result
        return {**state, "agent_results": results, "commit_result": commit_result}

    commit_result = {"committed": True, "hash": after_sha, "message": message, "paths": paths}
    results["commit"] = commit_result
    return {**state, "agent_results": results, "commit_result": commit_result}
