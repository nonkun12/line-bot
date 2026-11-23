"""Independent, read-only REA bridge for one-shot local repairs.

The scanner and pytest suite run in separate child processes. Post-repair scanning
uses a temporary Git index and an unreachable commit object, never changing HEAD,
the user's index, or repository refs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

CODE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_TIMEOUT = 1800


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        raise RuntimeError("rea_git_evidence_unavailable")
    return result.stdout.strip()


def _changed_paths(root: Path) -> list[str]:
    values = []
    for args in (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        values.extend(item for item in _git(root, *args).split("\0") if item)
    return sorted(set(values))


def _snapshot_commit(root: Path, base_sha: str, allowed_paths: list[str], expected_paths: list[str]) -> str:
    if not allowed_paths or not expected_paths:
        raise RuntimeError("rea_snapshot_paths_missing")
    actual = _changed_paths(root)
    if actual != sorted(set(expected_paths)) or not set(actual).issubset(set(allowed_paths)):
        raise RuntimeError("rea_snapshot_paths_mismatch")
    if _git(root, "rev-parse", "HEAD") != base_sha:
        raise RuntimeError("rea_snapshot_head_mismatch")

    with tempfile.TemporaryDirectory(prefix="rea-index-") as temp:
        index_path = str(Path(temp) / "index")
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = index_path
        env["GIT_AUTHOR_NAME"] = "REA verifier"
        env["GIT_AUTHOR_EMAIL"] = "rea-verifier@localhost.invalid"
        env["GIT_COMMITTER_NAME"] = "REA verifier"
        env["GIT_COMMITTER_EMAIL"] = "rea-verifier@localhost.invalid"
        _git(root, "read-tree", base_sha, env=env)
        _git(root, "add", "-A", "--", *sorted(set(allowed_paths)), env=env)
        tree_sha = _git(root, "write-tree", env=env)
        target_sha = _git(
            root, "commit-tree", tree_sha, "-p", base_sha,
            "-m", "temporary REA verification snapshot", env=env,
        )
    diff_paths = [
        item for item in _git(root, "diff", "--name-only", "-z", base_sha, target_sha).split("\0")
        if item
    ]
    if sorted(diff_paths) != sorted(set(expected_paths)):
        raise RuntimeError("rea_snapshot_diff_mismatch")
    return target_sha


def _run_scanner(root: Path, *, stage: str, base_sha: str, target_sha: str | None = None) -> dict[str, Any]:
    if stage == "PRE_REPAIR":
        code = (
            "import json,sys; from scripts.rea_readonly_scanner import scan_repository; "
            "print(json.dumps(scan_repository(sys.argv[1]), sort_keys=True))"
        )
        args = [sys.executable, "-c", code, str(root)]
    else:
        code = (
            "import json,sys; from scripts.rea_readonly_scanner import scan_commit_diff; "
            "print(json.dumps(scan_commit_diff(sys.argv[1], base_sha=sys.argv[2], "
            "target_sha=sys.argv[3]), sort_keys=True))"
        )
        args = [sys.executable, "-c", code, str(root), base_sha, str(target_sha)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CODE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        args, cwd=CODE_ROOT, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False, timeout=180,
    )
    if result.returncode:
        raise RuntimeError("rea_scanner_subprocess_failed")
    try:
        report = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise RuntimeError("rea_scanner_receipt_invalid") from None
    if not isinstance(report, dict) or report.get("complete") is not True or report.get("status") != "PASS":
        raise RuntimeError("rea_scanner_not_pass")
    if stage == "PRE_REPAIR" and report.get("target_sha") != base_sha:
        raise RuntimeError("rea_pre_repair_sha_mismatch")
    if stage == "POST_REPAIR" and (
        report.get("base_sha") != base_sha or report.get("target_sha") != target_sha
    ):
        raise RuntimeError("rea_post_repair_sha_mismatch")
    return report


def _run_pytest(root: Path, allowed_paths: list[str] | None = None) -> dict[str, Any]:
    test_paths = sorted({
        path for path in (allowed_paths or [])
        if isinstance(path, str) and path.startswith("tests/") and path.endswith(".py")
    })
    command = [sys.executable, "-m", "pytest", "-q", *test_paths]
    result = subprocess.run(
        command,
        cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, check=False, timeout=DEFAULT_TEST_TIMEOUT,
    )
    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
    }


def run_pre_repair_rea(
    repo_root: str | Path, *, base_sha: str, allowed_paths: list[str] | None = None
) -> dict[str, Any]:
    """Require a clean-base read-only scan and passing test suite before repair."""
    root = Path(repo_root).resolve()
    try:
        if _git(root, "rev-parse", "HEAD") != base_sha or _git(root, "status", "--porcelain", "--untracked-files=all"):
            raise RuntimeError("rea_pre_repair_repository_not_clean")
        report = _run_scanner(root, stage="PRE_REPAIR", base_sha=base_sha)
        tests = _run_pytest(root, allowed_paths)
        if tests["status"] != "PASS":
            raise RuntimeError("rea_pre_repair_tests_not_pass")
        return {
            "status": "PASS", "stage": "PRE_REPAIR", "base_sha": base_sha,
            "evaluated_paths": [], "independent": True,
            "scanner": "separate_read_only_subprocess",
            "tests": tests, "findings_count": report.get("findings_count", 0),
        }
    except Exception as exc:
        return {
            "status": "BLOCKED", "stage": "PRE_REPAIR", "base_sha": base_sha,
            "evaluated_paths": [], "independent": False,
            "reason_code": str(exc) if str(exc).startswith("rea_") else "rea_pre_repair_incomplete",
        }


def create_post_repair_rea_runner(repo_root: str | Path):
    """Create the callable required by loop_repair_executor.execute_one_repair."""
    root = Path(repo_root).resolve()

    def verify(request: dict[str, Any]) -> dict[str, Any]:
        base_sha = request.get("base_sha")
        allowed_paths = request.get("allowed_paths")
        expected_paths = request.get("changed_paths")
        if (
            request.get("stage") != "POST_REPAIR"
            or not isinstance(base_sha, str)
            or not isinstance(allowed_paths, list)
            or not isinstance(expected_paths, list)
        ):
            return {"status": "BLOCKED", "reason_code": "rea_post_request_invalid"}
        try:
            target_sha = _snapshot_commit(root, base_sha, allowed_paths, expected_paths)
            report = _run_scanner(
                root, stage="POST_REPAIR", base_sha=base_sha, target_sha=target_sha
            )
            tests = _run_pytest(root)
            if tests["status"] != "PASS":
                raise RuntimeError("rea_post_repair_tests_not_pass")
            return {
                "status": "PASS", "stage": "POST_REPAIR", "base_sha": base_sha,
                "target_sha": target_sha, "evaluated_paths": sorted(set(expected_paths)),
                "independent": True, "scanner": "separate_read_only_subprocess",
                "tests": tests, "diff_sha256": report.get("diff_sha256", ""),
                "findings_count": report.get("findings_count", 0),
            }
        except Exception as exc:
            return {
                "status": "BLOCKED", "stage": "POST_REPAIR", "base_sha": base_sha,
                "evaluated_paths": sorted(set(expected_paths)) if isinstance(expected_paths, list) else [],
                "independent": False,
                "reason_code": str(exc) if str(exc).startswith("rea_") else "rea_post_repair_incomplete",
            }

    return verify
