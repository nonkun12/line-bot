"""
Phase4b: Commit Agent

条件:
- pytest成功時のみcommitする
- pytest失敗時は何もしない
- Patch Agentが対象としたファイルだけをcommitする
- 事前に別ファイルがstage済みならcommitしない
- main/masterへ直接commitしない
- commit後に実際の変更ファイルを再検証する
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

        if pure.is_absolute() or ".." in pure.parts or path == ".":
            continue

        paths.append(path)

    return list(dict.fromkeys(paths))


def _result(state, commit_result):
    results = dict(state.get("agent_results", {}))
    results["commit"] = commit_result
    return {
        **state,
        "agent_results": results,
        "commit_result": commit_result,
    }


def commit_node(state):
    test_result = state.get("test_result", {})

    if not test_result.get("passed"):
        return _result(
            state,
            {"committed": False, "skipped": True, "reason": "pytest not passed"},
        )

    workdir = os.environ.get("REPO_WORKDIR", os.getcwd())
    paths = _candidate_paths(state)

    if not paths:
        return _result(
            state,
            {"committed": False, "skipped": True, "reason": "no safe patch target files"},
        )

    branch = _run_git(["branch", "--show-current"], cwd=workdir)
    if branch.returncode != 0:
        return _result(state, {"committed": False, "error": branch.stderr, "paths": paths})

    current_branch = branch.stdout.strip()
    if current_branch in {"main", "master"}:
        return _result(
            state,
            {
                "committed": False,
                "skipped": True,
                "reason": f"direct commit forbidden on {current_branch}",
                "branch": current_branch,
                "paths": paths,
            },
        )

    staged_before = _run_git(["diff", "--cached", "--name-only", "--"], cwd=workdir)
    if staged_before.returncode != 0:
        return _result(
            state,
            {"committed": False, "error": staged_before.stderr, "paths": paths},
        )

    pre_staged = sorted(path for path in staged_before.stdout.splitlines() if path.strip())
    if pre_staged:
        return _result(
            state,
            {
                "committed": False,
                "skipped": True,
                "reason": "pre-existing staged changes detected",
                "staged_paths": pre_staged,
                "paths": paths,
            },
        )

    add = _run_git(["add", "--", *paths], cwd=workdir)
    if add.returncode != 0:
        return _result(
            state,
            {"committed": False, "error": add.stderr, "paths": paths},
        )

    staged_after = _run_git(["diff", "--cached", "--name-only", "--"], cwd=workdir)
    if staged_after.returncode != 0:
        return _result(
            state,
            {"committed": False, "error": staged_after.stderr, "paths": paths},
        )

    expected_paths = sorted(set(paths))
    staged_paths = sorted(path for path in staged_after.stdout.splitlines() if path.strip())
    if staged_paths != expected_paths:
        return _result(
            state,
            {
                "committed": False,
                "skipped": True,
                "reason": "staged paths do not exactly match patch targets",
                "staged_paths": staged_paths,
                "expected_paths": expected_paths,
            },
        )

    message = (
        state.get("agent_results", {})
        .get("fix", {})
        .get("commit_message", "AI Debug Agent automatic fix")
    )
    if not isinstance(message, str) or not message.strip():
        message = "AI Debug Agent automatic fix"

    commit = _run_git(["commit", "-m", message], cwd=workdir)
    if commit.returncode != 0:
        return _result(
            state,
            {"committed": False, "error": commit.stderr, "paths": paths},
        )

    log = _run_git(["rev-parse", "HEAD"], cwd=workdir)
    if log.returncode != 0 or not log.stdout.strip():
        return _result(
            state,
            {
                "committed": False,
                "error": log.stderr or "unable to resolve HEAD after commit",
                "paths": paths,
                "verification": False,
            },
        )

    committed_paths = _run_git(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=workdir,
    )
    if committed_paths.returncode != 0:
        return _result(
            state,
            {
                "committed": False,
                "error": committed_paths.stderr,
                "paths": paths,
                "verification": False,
            },
        )

    actual_paths = sorted(path for path in committed_paths.stdout.splitlines() if path.strip())
    if actual_paths != expected_paths:
        return _result(
            state,
            {
                "committed": False,
                "error": "commit contains unexpected files",
                "paths": paths,
                "actual_paths": actual_paths,
                "expected_paths": expected_paths,
                "hash": log.stdout.strip(),
                "verification": False,
            },
        )

    return _result(
        state,
        {
            "committed": True,
            "hash": log.stdout.strip(),
            "message": message,
            "paths": paths,
            "branch": current_branch,
            "verification": True,
        },
    )
