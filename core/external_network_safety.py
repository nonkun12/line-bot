"""Fail-closed guard for newly introduced external capabilities in autonomous code changes.

The guard compares Python capability fingerprints between an approved base revision
and the produced revision. Existing external integrations remain usable; adding a
new network/process capability or a new literal HTTP(S) destination is blocked.
This is a defense-in-depth boundary, not a replacement for code review.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Top-level modules whose introduction can create network or arbitrary external I/O.
DANGEROUS_MODULES = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http",
        "http.client",
        "httpx",
        "imaplib",
        "paramiko",
        "poplib",
        "requests",
        "smtplib",
        "socket",
        "subprocess",
        "telnetlib",
        "urllib",
        "websocket",
    }
)

DANGEROUS_CALLS = frozenset(
    {
        "__import__",
        "builtins.__import__",
        "eval",
        "exec",
        "compile",
        "ctypes.CDLL",
        "ctypes.PyDLL",
        "ctypes.WinDLL",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
        "os.popen",
        "os.system",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.run",
        "urllib.request.urlopen",
        "urllib.request.Request",
    }
)

DANGEROUS_CALL_PREFIXES = (
    "requests.",
    "httpx.",
    "aiohttp.",
    "socket.",
    "ftplib.",
    "smtplib.",
    "imaplib.",
    "poplib.",
    "paramiko.",
    "websocket.",
    "os.spawn",
    "os.exec",
    "subprocess.",
)

URL_PATTERN = re.compile(r"^https?://[^\\s\"'<>]+$", re.IGNORECASE)
SAFETY_GUARD_PATH = "core/external_network_safety.py"


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def capability_fingerprint(source: str) -> frozenset[str]:
    """Return deterministic capabilities observable from Python syntax."""
    tree = ast.parse(source)
    capabilities: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                root = module.split(".", 1)[0]
                if root in DANGEROUS_MODULES or module in DANGEROUS_MODULES:
                    capabilities.add(f"import:{module}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in DANGEROUS_MODULES or module in DANGEROUS_MODULES:
                capabilities.add(f"import:{module}")
        elif isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            if name in DANGEROUS_CALLS or any(
                name.startswith(prefix) for prefix in DANGEROUS_CALL_PREFIXES
            ):
                capabilities.add(f"call:{name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if URL_PATTERN.match(value):
                capabilities.add(f"url:{value}")

    return frozenset(capabilities)


def new_external_capabilities(
    base_source: str,
    produced_source: str,
) -> tuple[str, ...]:
    base = capability_fingerprint(base_source)
    produced = capability_fingerprint(produced_source)
    return tuple(sorted(produced - base))


def assert_no_new_external_capabilities(
    base_source: str,
    produced_source: str,
    path: str,
) -> tuple[str, ...]:
    """Raise RuntimeError when a change introduces a new external capability."""
    if path.replace("\\", "/").lstrip("./") == SAFETY_GUARD_PATH:
        return ()

    new_capabilities = new_external_capabilities(base_source, produced_source)
    if new_capabilities:
        raise RuntimeError(
            "external capability safety gate blocked "
            f"{path}: {', '.join(new_capabilities)}"
        )
    return ()


def changed_python_paths(base_sha: str, produced_sha: str) -> tuple[str, ...]:
    if not base_sha or not produced_sha:
        raise ValueError("base and produced SHAs are required")
    result = subprocess.run(
        ["git", "diff", "--name-only", base_sha, produced_sha, "--", "*.py"],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "unable to inspect git diff")
    return tuple(path for path in result.stdout.splitlines() if path.strip())


def git_source(sha: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        # A newly-added Python file has an empty baseline.
        return ""
    return result.stdout


def check_revision(base_sha: str, produced_sha: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    findings: list[tuple[str, tuple[str, ...]]] = []
    for path in changed_python_paths(base_sha, produced_sha):
        produced = git_source(produced_sha, path)
        new_capabilities = new_external_capabilities(git_source(base_sha, path), produced)
        if new_capabilities and path != SAFETY_GUARD_PATH:
            findings.append((path, new_capabilities))
    if findings:
        details = "; ".join(f"{path}: {', '.join(items)}" for path, items in findings)
        raise RuntimeError(f"external capability safety gate blocked: {details}")
    return tuple(findings)


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 2:
        print("usage: python -m core.external_network_safety BASE_SHA PRODUCED_SHA")
        return 2
    try:
        check_revision(args[0], args[1])
    except Exception as exc:
        print(f"EXTERNAL_NETWORK_SAFETY=BLOCKED:{type(exc).__name__}:{exc}")
        return 1
    print("EXTERNAL_NETWORK_SAFETY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
