"""Fail-closed adapter for post-generation REA evidence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.rea_readonly_scanner import ScanBlocked, scan_commit_diff


class PostGenerationREABlocked(RuntimeError):
    """Raised when committed generated output lacks complete clean REA evidence."""


def verify_generated_commit(
    repo_root: str | Path, *, base_sha: str, target_sha: str
) -> dict[str, Any]:
    """Scan exact committed output and accept only complete, hash-bound PASS evidence."""
    try:
        report = scan_commit_diff(
            repo_root, base_sha=base_sha, target_sha=target_sha
        )
    except (ScanBlocked, OSError, ValueError, RuntimeError) as exc:
        raise PostGenerationREABlocked(
            f"post_generation_scan_unavailable:{type(exc).__name__}"
        ) from None

    if (
        report.get("base_sha") != base_sha
        or report.get("target_sha") != target_sha
        or not isinstance(report.get("diff_sha256"), str)
        or len(report["diff_sha256"]) != 64
        or report.get("complete") is not True
        or report.get("status") != "PASS"
        or report.get("findings_count") != 0
        or report.get("findings") != []
        or report.get("capabilities", {}).get("read_only") is not True
        or report.get("capabilities", {}).get("executes_project_code") is not False
    ):
        raise PostGenerationREABlocked("post_generation_rea_not_clean_pass")
    return report
