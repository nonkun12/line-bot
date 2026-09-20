"""Fail-closed verification of the live git worktree after agent execution.

This gate is deliberately independent from model output. It binds an execution
to a baseline commit and an allowed path manifest, then re-reads the live
worktree immediately after the executor returns.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class GitWorktreeSafetyGate:
    repository: str | Path
    baseline_sha: str
    allowed_paths: tuple[str, ...] = ()

    def verify(self, task, result, allowed_paths: tuple[str, ...]) -> bool:
        """Return True only when the live worktree matches the approved scope."""
        if not result.success:
            return False
        root = Path(self.repository)
        baseline = self.baseline_sha.strip()
        if not baseline or not _valid_sha(baseline):
            return False

        configured = _canonical_paths(self.allowed_paths)
        supplied = _canonical_paths(allowed_paths)
        if configured and supplied != configured:
            return False
        allowed = configured or supplied
        if not allowed or not _safe_manifest(allowed):
            return False

        try:
            head = _git(root, "rev-parse", "HEAD")
            if not head:
                return False
            if head != baseline:
                _git(root, "merge-base", "--is-ancestor", baseline, head)
            changed = _changed_paths(root, baseline)
        except (OSError, subprocess.SubprocessError):
            return False

        if not changed:
            # A successful no-op is safe: there is no worktree mutation to authorize.
            return not getattr(result, "changed_resources", ())
        return all(_within_scope(path, allowed) and _safe_worktree_path(root, path) for path in changed)


def _git(
    root: Path,
    *args: str,
    check: bool = True,
    strip_output: bool = True,
) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *args),
        check=check,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip() if strip_output else completed.stdout


def _changed_paths(root: Path, baseline: str) -> set[str]:
    tracked = _git(root, "diff", "--name-only", "--diff-filter=ACDMRTUXB", baseline)
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        strip_output=False,
    )
    paths = {line.strip() for line in tracked.splitlines() if line.strip()}
    for line in status.splitlines():
        if len(line) >= 4:
            paths.add(line[3:].strip().strip('"'))
    return {_canonical_path(path) for path in paths if path.strip()}


def _canonical_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({_canonical_path(path) for path in paths if str(path).strip()}))


def _canonical_path(path: str) -> str:
    value = str(path).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    value = PurePosixPath(value).as_posix()
    return value


def _safe_manifest(paths: tuple[str, ...]) -> bool:
    return all(
        path
        and not path.startswith("/")
        and path != ".."
        and not path.startswith("../")
        for path in paths
    )


def _safe_worktree_path(root: Path, path: str) -> bool:
    candidate = root / Path(path)
    try:
        root_resolved = root.resolve()
        if candidate.is_symlink():
            return False
        candidate.resolve().relative_to(root_resolved)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _within_scope(path: str, allowed: tuple[str, ...]) -> bool:
    return any(path == target or path.startswith(target.rstrip("/") + "/") for target in allowed)


def _valid_sha(value: str) -> bool:
    return len(value) in (40, 64) and all(ch in "0123456789abcdefABCDEF" for ch in value)


__all__ = ["GitWorktreeSafetyGate"]
