"""OS-level, fail-closed sandbox for model-generated pytest code."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from scripts.autonomous_task_target_allowlist import TARGETS


def run_pytest_sandboxed(
    command: Sequence[str],
    *,
    repo_root: Path,
    test_paths: Sequence[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Run pytest with no network, a read-only repository, and one writable test file.

    Bubblewrap namespaces are the security boundary. If bubblewrap or namespace
    creation is unavailable, return a non-zero result; never fall back to host
    execution.
    """
    args = list(command)

    def blocked(reason: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 125, "", f"TEST_SANDBOX_BLOCKED: {reason}")

    if len(test_paths) != 1 or test_paths[0] not in {test for _, test in TARGETS}:
        return blocked("exactly_one_allowlisted_test_file_required")
    relative = Path(test_paths[0])
    if relative.is_absolute() or ".." in relative.parts:
        return blocked("unsafe_test_path")
    root = repo_root.resolve()
    target = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return blocked("test_path_symlink")
    try:
        target_resolved = target.resolve(strict=True)
        target_resolved.relative_to(root)
    except (OSError, ValueError):
        return blocked("test_path_unavailable_or_outside_repository")
    if not target_resolved.is_file():
        return blocked("test_target_not_file")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return blocked("bubblewrap_unavailable")

    safe_path = os.environ.get("PATH", os.defpath)
    sandbox = [
        bwrap, "--unshare-all", "--die-with-parent", "--new-session",
        "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        "--tmpfs", "/tmp", "--bind", str(target_resolved), str(target_resolved),
        "--dir", "/tmp/home", "--clearenv",
        "--setenv", "PATH", safe_path,
        "--setenv", "HOME", "/tmp/home",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONPATH", str(root),
        "--setenv", "LANG", "C.UTF-8",
        "--chdir", str(root), "--", *args,
    ]
    try:
        return subprocess.run(
            sandbox, cwd=root, text=True, capture_output=True,
            timeout=timeout, env={"PATH": safe_path},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return blocked(type(exc).__name__)
