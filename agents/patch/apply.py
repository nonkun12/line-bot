"""Safe unified-diff patch application for interactive and autonomous agents."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import tempfile
import uuid

GIT_COMMAND_TIMEOUT = float(os.environ.get("GIT_COMMAND_TIMEOUT", "10.0"))

PROTECTED_PATTERNS = (
    ".env", ".env.*", "*.db", "*.sqlite", "*.sqlite3", ".git", ".git/*",
    "chat.db", "langgraph-checkpoints.sqlite3", "git_safety.py", "job_worker.py",
    "job_store.py", "job_lease.py", "job_approvals.py",
    "standalone-agent/graph/graph.py", "standalone-agent/graph/state.py",
    "standalone_agent_graph.py",
)


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_COMMAND_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=1, stdout=e.stdout or "",
            stderr=(e.stderr or "") + f"\n[TIMEOUT] git command timed out after {GIT_COMMAND_TIMEOUT}s",
        )


def _extract_patch_paths(patch_text: str) -> set[str]:
    paths: set[str] = set()
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line[6:].strip())
        elif line.startswith("--- a/"):
            paths.add(line[6:].strip())
    return {path for path in paths if path and path != "/dev/null"}


def _unsafe_patch_paths(patch_text: str) -> list[str]:
    unsafe = []
    for path in sorted(_extract_patch_paths(patch_text)):
        normalized = path.replace("\\", "/")
        normalized_path = os.path.normpath(normalized)
        if (
            normalized.startswith("/")
            or normalized_path in {".", ".."}
            or normalized_path.startswith("../")
            or ":" in normalized_path.split("/")[0]
        ):
            unsafe.append(path)
    return unsafe


def _protected_paths(patch_text: str) -> list[str]:
    blocked = list(_unsafe_patch_paths(patch_text))
    for path in sorted(_extract_patch_paths(patch_text)):
        normalized = os.path.normpath(path.replace("\\", "/")).replace("\\", "/")
        if any(fnmatch.fnmatch(normalized, pattern) for pattern in PROTECTED_PATTERNS) and path not in blocked:
            blocked.append(path)
    return blocked


def apply_patch(patch_text: str, workdir: str) -> dict:
    if not patch_text or not patch_text.strip():
        return {"applied": False, "branch": None, "error": "empty patch", "stdout": "", "stderr": ""}

    blocked = _protected_paths(patch_text)
    if blocked and os.environ.get("ALLOW_PROTECTED_AUTONOMOUS_CHANGES", "false").lower() != "true":
        return {
            "applied": False, "branch": None, "error": "protected path change rejected",
            "stdout": "", "stderr": "blocked paths: " + ", ".join(blocked),
            "protected_paths": blocked,
        }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(patch_text)
        patch_path = f.name

    try:
        check = _run_git(["apply", "--check", patch_path], cwd=workdir)
        if check.returncode != 0:
            return {"applied": False, "branch": None, "error": "patch check failed", "stdout": check.stdout, "stderr": check.stderr}

        branch_name = f"fix/auto-{uuid.uuid4().hex[:8]}"
        checkout = _run_git(["checkout", "-b", branch_name], cwd=workdir)
        if checkout.returncode != 0:
            return {"applied": False, "branch": None, "error": "branch creation failed", "stdout": checkout.stdout, "stderr": checkout.stderr}

        apply_result = _run_git(["apply", patch_path], cwd=workdir)
        if apply_result.returncode != 0:
            return {"applied": False, "branch": branch_name, "error": "patch apply failed", "stdout": apply_result.stdout, "stderr": apply_result.stderr}

        return {"applied": True, "branch": branch_name, "error": None, "stdout": apply_result.stdout, "stderr": apply_result.stderr}
    finally:
        os.unlink(patch_path)
