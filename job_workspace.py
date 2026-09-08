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


def workspace_for_job(job_id: int | str, repo_root: str | None = None) -> str:
    """Create and return a detached git worktree dedicated to one Job.

    The parent repository is never checked out to a job-specific branch. Each
    Job gets its own worktree directory, preventing concurrent Jobs from
    sharing an in-process working tree.
    """
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    root = Path(repo_root) / DEFAULT_WORKTREE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"job-{_safe_job_name(job_id)}"

    if path.exists():
        return str(path)

    result = _run_git(["worktree", "add", "--detach", str(path), "HEAD"], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree add failed")
    return str(path)


def remove_workspace(job_id: int | str, repo_root: str | None = None) -> bool:
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    path = Path(repo_root) / DEFAULT_WORKTREE_ROOT / f"job-{_safe_job_name(job_id)}"
    if not path.exists():
        return False
    result = _run_git(["worktree", "remove", "--force", str(path)], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree remove failed")
    return True
