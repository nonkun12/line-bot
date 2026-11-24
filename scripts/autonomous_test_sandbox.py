"""Fail-closed bubblewrap sandbox for one allowlisted pytest file.

Only the repository and Python runtime paths are visible, all read-only.
Writable state is confined to fresh tmpfs mounts. No host environment,
home directory, /run, credentials, or Unix sockets are inherited.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class SandboxError(RuntimeError):
    """The requested test could not be safely isolated."""


def _runtime_directories(python: str) -> list[Path]:
    candidates: set[Path] = set()
    executable = Path(python).resolve(strict=True)
    candidates.add(executable.parent)

    for raw in (sys.prefix, sys.base_prefix, *sys.path):
        if not raw:
            continue
        path = Path(raw)
        if path.exists() and path.is_dir():
            candidates.add(path.resolve())

    # Bind only directories containing the interpreter's actual ELF
    # dependencies, rather than exposing the host root or all of /etc.
    ldd = shutil.which("ldd")
    if ldd:
        result = subprocess.run(
            [ldd, str(executable)], text=True, capture_output=True, timeout=10,
            env={"PATH": os.defpath, "LANG": "C"},
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                match = re.search(r"=>\s+(/[^\s]+)|^\s*(/[^\s]+)", line)
                if match:
                    library = Path(match.group(1) or match.group(2))
                    if library.exists():
                        candidates.add(library.resolve().parent)

    # Never mount filesystem roots or broad user/credential locations.
    safe: set[Path] = set()
    for path in candidates:
        if not path.is_dir() or path == Path("/") or path == Path.home():
            continue
        safe.add(path)
    if not safe:
        raise SandboxError("python_runtime_paths_unavailable")
    return sorted(safe, key=lambda item: (len(item.parts), str(item)))


def _parents(destination: str) -> list[str]:
    parts = Path(destination).parts
    result: list[str] = []
    current = ""
    for part in parts[:-1]:
        current = str(Path(current) / part) if current else part
        if current not in ("/", ".") and current not in result:
            result.append(current)
    return result


def build_sandbox_command(
    repository: str | Path,
    test_path: str,
    *,
    python: str = sys.executable,
) -> list[str]:
    root = Path(repository).resolve(strict=True)
    if not root.is_dir():
        raise SandboxError("repository_not_directory")
    if (
        not isinstance(test_path, str)
        or not test_path.startswith("tests/")
        or not test_path.endswith(".py")
        or Path(test_path).is_absolute()
        or any(part in ("", ".", "..") for part in Path(test_path).parts)
        or "\\" in test_path
    ):
        raise SandboxError("test_path_not_allowlisted")

    target = root / test_path
    # Reject symlinks at every component, even if they resolve inside the repo.
    cursor = root
    for part in Path(test_path).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SandboxError("test_path_symlink_rejected")
    if not target.is_file() or not target.resolve().is_relative_to(root):
        raise SandboxError("test_path_missing_or_outside_repository")

    bwrap = shutil.which("bwrap")
    prlimit = shutil.which("prlimit")
    if not bwrap or not prlimit:
        raise SandboxError("sandbox_runtime_unavailable")

    runtime_dirs = _runtime_directories(python)
    # Empty root first: only explicitly selected runtime and repository paths
    # are mounted into the namespace.
    args = [
        prlimit, "--nproc=64", "--cpu=180", "--fsize=1048576",
        "--as=4294967296", "--", bwrap,
        "--die-with-parent", "--new-session", "--unshare-all",
        "--tmpfs", "/",
        "--dir", "/proc", "--proc", "/proc",
        "--dev", "/dev",
        "--dir", "/tmp", "--tmpfs", "/tmp",
        "--dir", "/run", "--tmpfs", "/run",
        "--dir", "/var", "--dir", "/var/run", "--tmpfs", "/var/run",
        "--dir", "/home", "--tmpfs", "/home",
    ]

    mounts: dict[str, Path] = {}
    for directory in runtime_dirs:
        mounts[str(directory)] = directory
    mounts[str(root)] = root

    destinations = sorted(mounts, key=lambda value: (len(Path(value).parts), value))
    created: set[str] = {"/", "/proc", "/dev", "/tmp", "/run", "/var", "/var/run", "/home"}
    for destination in destinations:
        for parent in _parents(destination):
            if parent not in created:
                args.extend(["--dir", parent])
                created.add(parent)
        args.extend(["--ro-bind", destination, destination])
        created.add(destination)

    args.extend([
        "--chdir", str(root),
        "--clearenv",
        "--setenv", "HOME", "/tmp",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "TMP", "/tmp",
        "--setenv", "PATH", os.defpath,
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--",
        str(Path(python).resolve(strict=True)), "-m", "pytest", "-q",
        "--tb=native", "-p", "no:cacheprovider", test_path,
    ])
    return args


def run_sandboxed_pytest(
    repository: str | Path,
    test_path: str,
    *,
    timeout: int = 900,
    python: str = sys.executable,
) -> subprocess.CompletedProcess[str]:
    command = build_sandbox_command(repository, test_path, python=python)
    try:
        return subprocess.run(
            command, cwd=repository, text=True, capture_output=True,
            timeout=timeout, env={"PATH": os.defpath, "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxError(f"sandbox_launch_failed:{type(exc).__name__}") from None
