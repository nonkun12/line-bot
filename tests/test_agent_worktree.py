from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.agent_worktree import IsolatedWorktreeManager, WorktreeError


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, timeout=15)
    git(repo, "config", "user.name", "Agent Worktree Tests")
    git(repo, "config", "user.email", "agent-worktree-tests@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD")


def test_create_uses_detached_commit_and_isolated_directory(repository, tmp_path):
    repo, commit = repository
    root = tmp_path / "workers"
    manager = IsolatedWorktreeManager(repo, root)

    worktree = manager.create("task-01", commit)

    assert worktree.commit_sha == commit
    assert worktree.path == root.resolve() / "task-01"
    assert worktree.path.is_dir()
    assert git(worktree.path, "rev-parse", "HEAD") == commit
    assert git(worktree.path, "rev-parse", "--is-inside-work-tree") == "true"
    assert manager.active == (worktree,)
    assert git(repo, "rev-parse", "HEAD") == commit


def test_remove_only_removes_registered_worktree(repository, tmp_path):
    repo, commit = repository
    root = tmp_path / "workers"
    manager = IsolatedWorktreeManager(repo, root)
    worktree = manager.create("task-02", commit)

    manager.remove("task-02")

    assert not worktree.path.exists()
    assert manager.active == ()
    assert "worktree" in git(repo, "worktree", "list")


@pytest.mark.parametrize("task_id", ["../escape", "nested/task", "", ".", "..", "a" * 81])
def test_rejects_unsafe_task_ids(repository, tmp_path, task_id):
    repo, commit = repository
    manager = IsolatedWorktreeManager(repo, tmp_path / "workers")

    with pytest.raises(WorktreeError, match="task_id"):
        manager.create(task_id, commit)


@pytest.mark.parametrize("base_ref", ["../HEAD", "-c", "HEAD..HEAD", "HEAD@", "bad ref", ""])
def test_rejects_unsafe_base_refs(repository, tmp_path, base_ref):
    repo, _ = repository
    manager = IsolatedWorktreeManager(repo, tmp_path / "workers")

    with pytest.raises(WorktreeError, match="base_ref"):
        manager.create("task-03", base_ref)


def test_rejects_duplicate_task_and_existing_target(repository, tmp_path):
    repo, commit = repository
    root = tmp_path / "workers"
    manager = IsolatedWorktreeManager(repo, root)
    manager.create("task-04", commit)

    with pytest.raises(WorktreeError, match="registered"):
        manager.create("task-04", commit)
    with pytest.raises(WorktreeError, match="already exists"):
        manager.create("task-05", commit) if (root / "task-05").mkdir() is None else None


def test_remove_refuses_unregistered_task(repository, tmp_path):
    repo, _ = repository
    manager = IsolatedWorktreeManager(repo, tmp_path / "workers")

    with pytest.raises(WorktreeError, match="no registered"):
        manager.remove("task-06")
