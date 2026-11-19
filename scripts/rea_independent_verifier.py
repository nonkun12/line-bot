"""Out-of-process, fail-closed verification for immutable REA artifacts.

This worker verifies the checked-out target commit, scans its exact base..target
diff, and runs the repository test suite in a separate subprocess. It never
reads test/risk claims from a runtime-generated summary and never grants
execution, patch, hold-clear, merge, or deploy authority.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.rea_readonly_scanner import ScanBlocked, scan_commit_diff

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TEST_TIMEOUT_SECONDS = 600
_HIGH_RISK_ROOTS = (".github/workflows/", "core/", "scripts/")
_LOW_RISK_ROOTS = ("tests/", "docs/rea/")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        timeout=15,
    )
    if result.returncode:
        raise ScanBlocked("git_evidence_unavailable")
    return result.stdout.strip()


def _risk_for_paths(paths: list[str]) -> str:
    """Use conservative path tiers; mixed or unclassified changes are HIGH."""
    if not paths:
        return "UNKNOWN"
    if any(path.startswith(_HIGH_RISK_ROOTS) for path in paths):
        return "HIGH"
    if all(path.startswith(_LOW_RISK_ROOTS) for path in paths):
        return "LOW"
    return "HIGH"


def collect_independent_verification(
    *,
    repo_root: str | Path,
    base_sha: str,
    target_sha: str,
    stop_state: str = "UNKNOWN",
    hold_state: str = "UNKNOWN",
) -> dict[str, Any]:
    """Verify an exact clean checkout and run pytest without trusting runner claims.

    The test process runs with argv (never a shell string), a fixed command,
    closed stdin, discarded output, and a hard timeout. Only its exit status is
    returned. STOP/HOLD are caller-supplied authoritative states; absent values
    remain UNKNOWN and therefore cannot produce a PASS in the REA evaluator.
    """
    root = Path(repo_root).resolve()
    result: dict[str, Any] = {
        "base_sha": base_sha,
        "target_sha": target_sha,
        "changed_files": [],
        "tests": "UNKNOWN",
        "diff_scan": "UNKNOWN",
        "risk": "UNKNOWN",
        "stop_state": stop_state,
        "hold_state": hold_state,
        "verifier": "rea-independent-subprocess-v1",
        "test_command": ["python", "-m", "pytest", "-q"],
        "test_exit_code": None,
    }
    try:
        if not root.is_dir() or not _SHA_RE.fullmatch(base_sha) or not _SHA_RE.fullmatch(target_sha):
            raise ScanBlocked("verification_input_invalid")
        if _git(root, "rev-parse", "HEAD") != target_sha:
            raise ScanBlocked("checkout_target_sha_mismatch")
        if _git(root, "status", "--porcelain", "--untracked-files=all"):
            raise ScanBlocked("verification_worktree_not_clean")

        scan = scan_commit_diff(root, base_sha=base_sha, target_sha=target_sha)
        paths = scan.get("changed_paths")
        if scan.get("status") != "PASS" or scan.get("complete") is not True:
            result["diff_scan"] = "FAIL"
            result["changed_files"] = paths if isinstance(paths, list) else []
            result["diff_sha256"] = scan.get("diff_sha256")
            result["risk"] = "HIGH"
            return result
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ScanBlocked("changed_path_evidence_invalid")

        result["changed_files"] = paths
        result["diff_scan"] = "PASS"
        result["diff_sha256"] = scan.get("diff_sha256")
        result["risk"] = _risk_for_paths(paths)

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=_TEST_TIMEOUT_SECONDS,
            shell=False,
        )
        result["test_exit_code"] = completed.returncode
        result["tests"] = "PASS" if completed.returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired:
        result["tests"] = "UNKNOWN"
        result["reason_code"] = "independent_test_timeout"
    except (OSError, ValueError, TypeError, ScanBlocked, subprocess.SubprocessError):
        result["reason_code"] = "independent_verification_unavailable"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--stop-state", choices=("INACTIVE", "ACTIVE", "UNKNOWN"), default="UNKNOWN")
    parser.add_argument("--hold-state", choices=("CLEAR", "ACTIVE", "UNKNOWN"), default="UNKNOWN")
    args = parser.parse_args(argv)
    evidence = collect_independent_verification(
        repo_root=args.repo_root,
        base_sha=args.base_sha,
        target_sha=args.target_sha,
        stop_state=args.stop_state,
        hold_state=args.hold_state,
    )
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["tests"] == "PASS" and evidence["diff_scan"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
