"""Per-Job git worktree management for isolated overnight development."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_WORKTREE_ROOT = os.environ.get("JOB_WORKTREE_ROOT", ".worker-worktrees")
GIT_LOCK_RETRIES = int(os.environ.get("GIT_LOCK_RETRIES", "3"))
GIT_LOCK_BACKOFF_SECONDS = float(os.environ.get("GIT_LOCK_BACKOFF_SECONDS", "0.5"))


def _is_git_lock_error(result: subprocess.CompletedProcess) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "index.lock" in text or "could not lock ref" in text or ("unable to create" in text and ".lock" in text)


def _run_git(args: list[str], cwd: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    command = ["git", *args]
    last_result: subprocess.CompletedProcess | None = None
    for attempt in range(max(1, GIT_LOCK_RETRIES + 1)):
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        last_result = result
        if result.returncode == 0 or not _is_git_lock_error(result) or attempt >= GIT_LOCK_RETRIES:
            return result
        time.sleep(GIT_LOCK_BACKOFF_SECONDS * (2 ** attempt))
    return last_result or subprocess.CompletedProcess(command, 1, "", "git command failed")


def prune_worktrees(repo_root: str | None = None) -> bool:
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    result = _run_git(["worktree", "prune"], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree prune failed")
    return True


def _safe_job_name(job_id: int | str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(job_id))


def _worktree_path(job_id: int | str, repo_root: str) -> Path:
    return Path(repo_root) / DEFAULT_WORKTREE_ROOT / f"job-{_safe_job_name(job_id)}"


def _fresh_base_ref(repo_root: str) -> str:
    fetch = _run_git(["fetch", "origin", "main"], cwd=repo_root)
    return "origin/main" if fetch.returncode == 0 else "HEAD"


def workspace_for_job(job_id: int | str, repo_root: str | None = None, branch: str | None = None) -> str:
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    root = Path(repo_root) / DEFAULT_WORKTREE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    prune_worktrees(repo_root)
    path = _worktree_path(job_id, repo_root)
    if path.exists():
        return str(path)

    if branch:
        remote_ref = f"origin/{branch}"
        fetch = _run_git(["fetch", "origin", branch], cwd=repo_root)
        start_ref = remote_ref if fetch.returncode == 0 else None
        if start_ref is None:
            local_ref = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo_root)
            if local_ref.returncode == 0:
                start_ref = branch
        if start_ref is None:
            raise RuntimeError(f"job branch {branch!r} is not available locally or on origin")
        local_branch = _run_git(["show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo_root)
        if local_branch.returncode == 0:
            result = _run_git(["worktree", "add", str(path), branch], cwd=repo_root)
        else:
            result = _run_git(["worktree", "add", "-b", branch, str(path), start_ref], cwd=repo_root)
    else:
        result = _run_git(["worktree", "add", "--detach", str(path), _fresh_base_ref(repo_root)], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree add failed")
    return str(path)


def restore_workspace_for_job(job_id: int | str, branch: str, repo_root: str | None = None) -> str:
    if not branch:
        raise ValueError("job branch is required for workspace restore")
    return workspace_for_job(job_id, repo_root=repo_root, branch=branch)


def remove_workspace(job_id: int | str, repo_root: str | None = None) -> bool:
    repo_root = os.path.abspath(repo_root or os.environ.get("REPO_ROOT") or os.getcwd())
    path = _worktree_path(job_id, repo_root)
    if not path.exists():
        prune_worktrees(repo_root)
        return False
    result = _run_git(["worktree", "remove", "--force", str(path)], cwd=repo_root)
    if result.returncode != 0:
        # Some older/minimal Git builds lack `worktree remove`. Remove the
        # filesystem directory and prune stale metadata as a safe fallback.
        if path.exists():
            shutil.rmtree(path)
        prune_worktrees(repo_root)
        return True
    prune_worktrees(repo_root)
    return True
