"""Fail-closed lifecycle manager for isolated Git worktrees used by agent workers.

This module only prepares and removes detached worktrees. It does not run agents,
merge branches, deploy, or modify the primary checkout's working tree.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")


class WorktreeError(RuntimeError):
    """Raised when an isolated worktree cannot be safely prepared or removed."""


@dataclass(frozen=True)
class IsolatedWorktree:
    task_id: str
    path: Path
    commit_sha: str


class IsolatedWorktreeManager:
    """Create detached task worktrees under one dedicated, caller-owned root.

    The manager intentionally requires an explicit base ref and keeps a registry
    of worktrees it created. Cleanup is allowed only for registered paths under
    the configured root; arbitrary filesystem paths are never recursively deleted.
    """

    def __init__(self, repository: str | Path, worktree_root: str | Path) -> None:
        self.repository = Path(repository).expanduser().resolve()
        self.worktree_root = Path(worktree_root).expanduser().resolve()
        self._created: dict[str, IsolatedWorktree] = {}

    @staticmethod
    def _git(repository: Path, *args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(repository), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorktreeError(f"git {' '.join(args[:2])} failed: {type(exc).__name__}") from exc
        return completed.stdout.strip()

    def create(self, task_id: str, base_ref: str) -> IsolatedWorktree:
        """Create one detached worktree at a resolved commit, refusing collisions."""
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or task_id in {".", ".."}:
            raise WorktreeError("invalid task_id")
        if not isinstance(base_ref, str) or not _REF.fullmatch(base_ref):
            raise WorktreeError("invalid base_ref")
        if ".." in base_ref or "@{" in base_ref or base_ref.endswith("/"):
            raise WorktreeError("invalid base_ref")

        if task_id in self._created:
            raise WorktreeError("task already has a registered worktree")
        self._git(self.repository, "rev-parse", "--show-toplevel")
        commit_sha = self._git(self.repository, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit_sha):
            raise WorktreeError("git returned an invalid commit id")

        self.worktree_root.mkdir(parents=True, exist_ok=True)
        target = (self.worktree_root / task_id).resolve()
        if target.parent != self.worktree_root or target.exists():
            raise WorktreeError("worktree target already exists or escapes configured root")

        self._git(self.repository, "worktree", "add", "--detach", str(target), commit_sha)
        worktree = IsolatedWorktree(task_id=task_id, path=target, commit_sha=commit_sha)
        self._created[task_id] = worktree
        return worktree

    def remove(self, task_id: str) -> None:
        """Remove only a worktree this manager successfully created."""
        worktree = self._created.get(task_id)
        if worktree is None:
            raise WorktreeError("no registered worktree for task")
        resolved = worktree.path.resolve()
        if resolved.parent != self.worktree_root or resolved != self.worktree_root / task_id:
            raise WorktreeError("registered worktree path escaped configured root")
        self._git(self.repository, "worktree", "remove", "--force", str(resolved))
        del self._created[task_id]

    @property
    def active(self) -> tuple[IsolatedWorktree, ...]:
        """Return a stable snapshot of currently registered worktrees."""
        return tuple(self._created[key] for key in sorted(self._created))
