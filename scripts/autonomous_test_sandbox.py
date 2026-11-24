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
import sysconfig
from pathlib import Path


class SandboxError(RuntimeError):
    """The requested test could not be safely isolated."""


def _runtime_directories(python: str) -> list[Path]:
    candidates: set[Path] = set()
    executable = Path(python).resolve(strict=True)
    candidates.add(executable.parent)

    configured = sysconfig.get_paths()
    runtime_roots: list[Path] = []
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        raw = configured.get(key)
        if raw:
            path = Path(raw)
            if path.exists() and path.is_dir():
                resolved = path.resolve()
                candidates.add(resolved)
                runtime_roots.append(resolved)
    # Include the interpreter's extension-module directory only when it is
    # nested under the configured standard library, never arbitrary PYTHONPATH
    # or user-site directories inherited from the host process.
    for raw in sys.path:
        if not raw:
            continue
        path = Path(raw)
        if not path.exists() or not path.is_dir():
            continue
        resolved = path.resolve()
        if any(resolved.is_relative_to(base) for base in runtime_roots):
            candidates.add(resolved)

    # Include only the standard command directory and git when present; some
    # allowlisted regression tests create temporary local git repositories.
    git = shutil.which("git")
    executables = [executable]
    if git:
        git_executable = Path(git).resolve(strict=True)
        candidates.add(git_executable.parent)
        executables.append(git_executable)

    # Bind only directories containing actual ELF dependencies, rather than
    # exposing the host root, all of /etc, or the whole Python prefix.
    ldd = shutil.which("ldd")
    if ldd:
        for binary in executables:
            result = subprocess.run(
                [ldd, str(binary)], text=True, capture_output=True, timeout=10,
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
    current = Path("/")
    for part in parts[1:-1]:
        current = current / part
        value = str(current)
        if value not in result:
            result.append(value)
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
    # /bin is commonly a symlink to /usr/bin on hosted Ubuntu runners. The
    # namespace starts empty, so provide both conventional command paths.
    if Path("/usr/bin").is_dir():
        mounts["/usr/bin"] = Path("/usr/bin").resolve()
        mounts["/bin"] = Path("/usr/bin").resolve()
    git_dir = Path("/usr/lib/git-core")
    if git_dir.is_dir():
        mounts[str(git_dir)] = git_dir.resolve()
    git_templates = Path("/usr/share/git-core")
    if git_templates.is_dir():
        mounts[str(git_templates)] = git_templates.resolve()
    mounts[str(root)] = root

    destinations = sorted(mounts, key=lambda value: (len(Path(value).parts), value))
    created: set[str] = {"/", "/proc", "/dev", "/tmp", "/run", "/var", "/var/run", "/home"}
    for destination in destinations:
        for parent in _parents(destination):
            if parent not in created:
                args.extend(["--dir", parent])
                created.add(parent)
        if destination not in created:
            args.extend(["--dir", destination])
            created.add(destination)
    for destination in destinations:
        source = str(mounts[destination])
        args.extend(["--ro-bind", source, destination])

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
