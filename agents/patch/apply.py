"""
Phase4a: Patch適用処理

安全設計:
- git apply --check で事前検証してから適用する(検証失敗時は一切書き込まない)
- 適用は専用の一時ブランチ上で行い、作業中のブランチを直接汚さない
"""

import os
import subprocess
import tempfile
import uuid


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def apply_patch(patch_text: str, workdir: str) -> dict:
    """
    unified diff形式のpatchを検証・適用する。

    Args:
        patch_text: unified diff形式のpatch文字列
        workdir: gitリポジトリのルートディレクトリ

    Returns:
        dict:
            applied: bool        適用に成功したか
            branch: Optional[str] 適用に使った一時ブランチ名
            error: Optional[str]  失敗理由(成功時はNone)
            stdout: str
            stderr: str
    """

    if not patch_text or not patch_text.strip():
        return {
            "applied": False,
            "branch": None,
            "error": "empty patch",
            "stdout": "",
            "stderr": "",
        }

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".patch",
        delete=False,
    ) as f:
        f.write(patch_text)
        patch_path = f.name

    try:
        # 1. 事前検証(書き込みは行わない)
        check = _run_git(
            ["apply", "--check", patch_path],
            cwd=workdir,
        )

        if check.returncode != 0:
            return {
                "applied": False,
                "branch": None,
                "error": "patch check failed",
                "stdout": check.stdout,
                "stderr": check.stderr,
            }

        # 2. 隔離用の一時ブランチを作成
        branch_name = f"fix/auto-{uuid.uuid4().hex[:8]}"

        checkout = _run_git(
            ["checkout", "-b", branch_name],
            cwd=workdir,
        )

        if checkout.returncode != 0:
            return {
                "applied": False,
                "branch": None,
                "error": "branch creation failed",
                "stdout": checkout.stdout,
                "stderr": checkout.stderr,
            }

        # 3. 実際に適用
        apply_result = _run_git(
            ["apply", patch_path],
            cwd=workdir,
        )

        if apply_result.returncode != 0:
            return {
                "applied": False,
                "branch": branch_name,
                "error": "patch apply failed",
                "stdout": apply_result.stdout,
                "stderr": apply_result.stderr,
            }

        return {
            "applied": True,
            "branch": branch_name,
            "error": None,
            "stdout": apply_result.stdout,
            "stderr": apply_result.stderr,
        }

    finally:
        os.unlink(patch_path)
