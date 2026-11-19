"""
Patch apply interface

git applyを利用して
patch検証・適用を行う。
"""

import subprocess
from dataclasses import dataclass


@dataclass
class ApplyResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    applied_files: list[str] | None = None


def validate_patch(
    patch: str,
    repo_root: str = ".",
) -> ApplyResult:
    """
    patch適用可能か確認する
    """

    if not patch.strip():
        return ApplyResult(
            success=False,
            stderr="empty patch"
        )

    result = subprocess.run(
        [
            "git",
            "apply",
            "--check",
            "-"
        ],
        input=patch,
        text=True,
        capture_output=True,
        cwd=repo_root,
    )

    return ApplyResult(
        success=result.returncode == 0,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def apply_patch(
    patch: str,
    repo_root: str = ".",
) -> ApplyResult:
    """
    patchを実際に適用する
    """

    check = validate_patch(
        patch,
        repo_root
    )

    if not check.success:
        return check


    result = subprocess.run(
        [
            "git",
            "apply",
            "-"
        ],
        input=patch,
        text=True,
        capture_output=True,
        cwd=repo_root,
    )


    return ApplyResult(
        success=result.returncode == 0,
        stdout=result.stdout,
        stderr=result.stderr,
    )
