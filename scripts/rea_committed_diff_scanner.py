"""Read-only REA review of the exact committed output diff before publication."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import PurePosixPath
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_ROOTS = (".github/workflows/", "core/", "scripts/", "tests/", "docs/rea/", "agents/")
_ALLOWED_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".md", ".txt"}
_DANGEROUS_ADDITION = re.compile(
    r"^[+].*\b(AUTO_APPLY_PATCH|AUTO_DEPLOY)\b.*(?:[:=]\s*[\"']?(?:true|yes|1)\b)",
    re.IGNORECASE,
)
_SECRET_ADDITION = re.compile(
    r"^[+].*(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)",
)
_GUARD_TERMS = (
    "AUTO_APPLY_PATCH", "AUTO_DEPLOY", "execution_authorized",
    "patch_authorized", "publish_authorized", "emergency_stop",
    "rea_gate", "rea_evidence", "GITHUB_TOKEN", "permissions:",
)
_TEST_REMOVAL = re.compile(r"^-[ \t]*(?:async[ \t]+)?def[ \t]+test_[A-Za-z0-9_]+\s*\(")
_ASSERT_REMOVAL = re.compile(r"^-[ \t]*assert\b")


class DiffScanBlocked(RuntimeError):
    """The exact candidate diff could not be established completely."""


def _git(root: str, *args: str, binary: bool = False):
    result = subprocess.run(
        ["git", *args], cwd=root, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=20,
    )
    if result.returncode:
        raise DiffScanBlocked("git_diff_evidence_unavailable")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="strict")


def scan_committed_diff(
    repo_root: str,
    *,
    base_sha: str,
    produced_sha: str,
    allowed_paths: list[str],
) -> dict[str, Any]:
    """Inspect immutable base..produced commit content; never modifies the repository."""
    if not _SHA.fullmatch(str(base_sha)) or not _SHA.fullmatch(str(produced_sha)):
        raise DiffScanBlocked("commit_sha_invalid")
    if not isinstance(allowed_paths, list) or not allowed_paths:
        raise DiffScanBlocked("allowed_paths_missing")
    if any(
        not isinstance(p, str) or not p or p != p.strip() or p.startswith("/")
        or "\\" in p or any(part in {"", ".", ".."} for part in p.split("/"))
        for p in allowed_paths
    ) or len(set(allowed_paths)) != len(allowed_paths):
        raise DiffScanBlocked("allowed_paths_invalid")

    _git(repo_root, "merge-base", "--is-ancestor", base_sha, produced_sha)
    names = _git(repo_root, "diff", "--no-renames", "--name-only", "-z", base_sha, produced_sha).split("\0")
    paths = sorted(p for p in names if p)
    if len(paths) > 100:
        raise DiffScanBlocked("diff_file_limit_exceeded")
    allowed = set(allowed_paths)
    if set(paths) - allowed:
        raise DiffScanBlocked("changed_path_outside_approval_scope")
    for path in paths:
        pure = PurePosixPath(path)
        if (
            pure.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/"))
            or not any(path.startswith(root) for root in _ALLOWED_ROOTS)
            or pure.suffix.lower() not in _ALLOWED_SUFFIXES
        ):
            raise DiffScanBlocked("changed_path_not_scannable")

    raw = _git(
        repo_root, "diff", "--no-ext-diff", "--no-renames", "--no-color",
        "--unified=0", "--no-textconv", base_sha, produced_sha, "--", binary=True,
    )
    if len(raw) > 2 * 1024 * 1024:
        raise DiffScanBlocked("diff_size_limit_exceeded")
    try:
        diff = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DiffScanBlocked("diff_encoding_unsupported") from None

    findings: list[dict[str, str]] = []
    removed_guard_terms: set[str] = set()
    removed_tests = 0
    removed_assertions = 0
    added_sensitive_lines = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            if _DANGEROUS_ADDITION.search(line) or _SECRET_ADDITION.search(line):
                added_sensitive_lines += 1
        elif line.startswith("-"):
            for term in _GUARD_TERMS:
                if term in line:
                    removed_guard_terms.add(term)
            if _TEST_REMOVAL.search(line):
                removed_tests += 1
            if _ASSERT_REMOVAL.search(line):
                removed_assertions += 1

    if added_sensitive_lines:
        findings.append({"code": "dangerous_flag_or_secret_added", "severity": "CRITICAL"})
    if removed_guard_terms:
        findings.append({"code": "safety_guard_removed_or_changed", "severity": "HIGH"})
    if removed_tests or removed_assertions:
        findings.append({"code": "regression_test_removed_or_weakened", "severity": "HIGH"})

    diff_sha256 = hashlib.sha256(raw).hexdigest()
    status = "PASS" if not findings else "BLOCKED"
    return {
        "schema_version": 1,
        "scanner": "rea-committed-diff-v1",
        "status": status,
        "complete": True,
        "base_sha": base_sha,
        "produced_sha": produced_sha,
        "diff_sha256": diff_sha256,
        "changed_paths": paths,
        "findings": findings,
        "findings_count": len(findings),
        "execution_authorized": False,
        "patch_authorized": False,
        "publish_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
