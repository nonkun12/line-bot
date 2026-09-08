"""Per-Job git worktree management for isolated overnight development."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

DEFAULT_WORKTREE_ROOT = os.environ.get("JOB_WORKTREE_ROOT", ".worker-worktrees")


def _run_git(args: list[str], cwd: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )


def _safe_job_name(job_id: int | str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(job_id))


def _worktree_path(job_id: int | str, repo_root: str) -> Path:
    return Path(repo_root) / DEFAULT_WORKTREE_ROOT / f"job-{_safe_job_name(job_id)}"


def workspace_for_job(
    job_id: int | str,
    repo_root: str | None = None,
    branch: str | None = None,
) -> str:
    """Create or reuse a per-Job worktree.

    A fresh Job starts from the current repository HEAD. A resumed Job may pass
    its remote Job branch so the worktree can be rebuilt after worker restart
    or ephemeral disk loss without discarding committed progress.
    """
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    root = Path(repo_root) / DEFAULT_WORKTREE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    path = _worktree_path(job_id, repo_root)

    if path.exists():
        return str(path)

    start_ref = "HEAD"
    if branch:
        remote_ref = f"origin/{branch}"
        fetch = _run_git(["fetch", "origin", branch], cwd=repo_root)
        if fetch.returncode == 0:
            start_ref = remote_ref
        else:
            local_ref = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo_root)
            if local_ref.returncode == 0:
                start_ref = branch

    if branch and start_ref != "HEAD":
        local_branch = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo_root)
        if local_branch.returncode == 0:
            result = _run_git(["worktree", "add", str(path), branch], cwd=repo_root)
        else:
            result = _run_git(["worktree", "add", "-b", branch, str(path), start_ref], cwd=repo_root)
    else:
        result = _run_git(["worktree", "add", "--detach", str(path), "HEAD"], cwd=repo_root)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree add failed")
    return str(path)


def restore_workspace_for_job(
    job_id: int | str,
    branch: str,
    repo_root: str | None = None,
) -> str:
    """Rebuild a missing Job worktree from its remote/local branch."""
    if not branch:
        raise ValueError("job branch is required for workspace restore")
    return workspace_for_job(job_id, repo_root=repo_root, branch=branch)


def remove_workspace(job_id: int | str, repo_root: str | None = None) -> bool:
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    path = _worktree_path(job_id, repo_root)
    if not path.exists():
        return False
    result = _run_git(["worktree", "remove", "--force", str(path)], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree remove failed")
    return True
