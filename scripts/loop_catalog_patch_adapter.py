"""Apply an explicitly catalog-approved unified diff without any model/API."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

MAX_PATCH_BYTES = 48_000


def _git(root: Path, *args: str, patch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], input=patch,
        capture_output=True, text=True, check=False, timeout=20,
    )


def _paths(patch: str) -> list[str] | None:
    if (
        not isinstance(patch, str)
        or not patch
        or len(patch.encode("utf-8")) > MAX_PATCH_BYTES
        or not patch.startswith("--- ")
        or "\n+++ " not in patch
        or "\n@@ " not in patch
    ):
        return None
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith(("diff --git ", "index ", "new file mode ", "deleted file mode ",
                            "old mode ", "new mode ", "rename from ", "rename to ",
                            "copy from ", "copy to ", "GIT binary patch")):
            return None
        if line.startswith("--- ") or line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0]
            prefix = "a/" if line.startswith("--- ") else "b/"
            if raw == "/dev/null" or not raw.startswith(prefix):
                return None
            path = raw[2:]
            if (
                not path or path.startswith("/") or "\\" in path
                or any(part in {"", ".", ".."} or part.lower() == ".git" for part in path.split("/"))
            ):
                return None
            paths.append(path)
    if not paths or len(paths) % 2:
        return None
    pairs = [paths[i:i + 2] for i in range(0, len(paths), 2)]
    if any(pair[0] != pair[1] for pair in pairs):
        return None
    result = sorted(set(paths))
    return result if len(result) * 2 == len(paths) else None


def create_catalog_patch_adapter(repo_root: str | Path, patch: str, expected_sha256: str):
    root = Path(repo_root).resolve()

    def repair(request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict) or request.get("provider_policy") != "provider_free_only":
            return {"status": "BLOCKED", "reason_code": "provider_policy_invalid"}
        if (
            not isinstance(expected_sha256, str)
            or hashlib.sha256(patch.encode("utf-8")).hexdigest() != expected_sha256
        ):
            return {"status": "BLOCKED", "reason_code": "catalog_patch_hash_mismatch"}
        allowed = request.get("allowed_paths")
        if not isinstance(allowed, list) or not allowed or not all(isinstance(x, str) for x in allowed):
            return {"status": "BLOCKED", "reason_code": "repair_paths_invalid"}
        touched = _paths(patch)
        if touched is None or not set(touched).issubset(set(allowed)):
            return {"status": "BLOCKED", "reason_code": "catalog_patch_paths_outside_allowlist"}
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        if (
            head.returncode or head.stdout.strip() != request.get("base_sha")
            or status.returncode or status.stdout.strip()
        ):
            return {"status": "BLOCKED", "reason_code": "repository_not_at_clean_authorized_base"}
        check = _git(root, "apply", "--check", patch=patch)
        if check.returncode:
            return {"status": "BLOCKED", "reason_code": "catalog_patch_does_not_apply"}
        applied = _git(root, "apply", patch=patch)
        if applied.returncode:
            return {"status": "BLOCKED", "reason_code": "catalog_patch_apply_failed"}
        changed = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        staged = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=False, timeout=20,
        )
        actual = sorted(set(changed.stdout.splitlines() + staged.stdout.splitlines() + untracked.stdout.splitlines()))
        if (
            changed.returncode or staged.returncode or untracked.returncode
            or actual != touched or not set(actual).issubset(set(allowed))
        ):
            return {"status": "BLOCKED", "reason_code": "catalog_patch_post_apply_scope_mismatch"}
        return {
            "status": "PASS",
            "reason_code": "catalog_approved_patch_applied",
            "provider": "preapproved_deterministic_catalog_patch",
            "changed_paths": actual,
        }

    return repair
