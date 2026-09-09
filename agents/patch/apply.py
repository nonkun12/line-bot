"""
Phase4a: Patch適用処理

安全設計:
- git apply --check で事前検証してから適用する(検証失敗時は一切書き込まない)
- 適用前に作業ツリーがcleanであることを確認し、既存変更との混入を防ぐ
- 適用は専用の一時ブランチ上で行い、作業中のブランチを直接汚さない
- 適用失敗時は元ブランチへ戻し、一時ブランチを削除する
"""

import os
import subprocess
import tempfile
import uuid


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def _cleanup_failed_branch(branch_name: str, original_branch: str, workdir: str) -> str | None:
    """失敗時に一時ブランチを片付け、元ブランチへ戻す。"""
    checkout = _run_git(["checkout", original_branch], cwd=workdir)
    if checkout.returncode != 0:
        return f"failed to restore original branch: {checkout.stderr}"
    delete = _run_git(["branch", "-D", branch_name], cwd=workdir)
    if delete.returncode != 0:
        return f"failed to delete temporary branch: {delete.stderr}"
    return None


def apply_patch(patch_text: str, workdir: str) -> dict:
    """unified diff形式のpatchを検証・適用する。"""
    if not patch_text or not patch_text.strip():
        return {"applied": False, "branch": None, "error": "empty patch", "stdout": "", "stderr": ""}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(patch_text)
        patch_path = f.name

    try:
        status = _run_git(["status", "--porcelain"], cwd=workdir)
        if status.returncode != 0:
            return {"applied": False, "branch": None, "error": "git status failed", "stdout": status.stdout, "stderr": status.stderr}
        if status.stdout.strip():
            return {"applied": False, "branch": None, "error": "dirty working tree is not supported for automatic patch apply", "stdout": status.stdout, "stderr": ""}

        check = _run_git(["apply", "--check", patch_path], cwd=workdir)
        if check.returncode != 0:
            return {"applied": False, "branch": None, "error": "patch check failed", "stdout": check.stdout, "stderr": check.stderr}

        original_branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=workdir)
        if original_branch_result.returncode != 0:
            return {"applied": False, "branch": None, "error": "current branch lookup failed", "stdout": original_branch_result.stdout, "stderr": original_branch_result.stderr}
        original_branch = original_branch_result.stdout.strip()
        if not original_branch or original_branch == "HEAD":
            return {"applied": False, "branch": None, "error": "detached HEAD is not supported", "stdout": "", "stderr": ""}

        branch_name = f"fix/auto-{uuid.uuid4().hex[:8]}"
        checkout = _run_git(["checkout", "-b", branch_name], cwd=workdir)
        if checkout.returncode != 0:
            return {"applied": False, "branch": None, "error": "branch creation failed", "stdout": checkout.stdout, "stderr": checkout.stderr}

        apply_result = _run_git(["apply", patch_path], cwd=workdir)
        if apply_result.returncode != 0:
            cleanup_error = _cleanup_failed_branch(branch_name, original_branch, workdir)
            error = "patch apply failed"
            if cleanup_error:
                error = f"{error}; {cleanup_error}"
            return {"applied": False, "branch": None if cleanup_error is None else branch_name, "error": error, "stdout": apply_result.stdout, "stderr": apply_result.stderr}

        return {"applied": True, "branch": branch_name, "error": None, "stdout": apply_result.stdout, "stderr": apply_result.stderr}
    finally:
        os.unlink(patch_path)
