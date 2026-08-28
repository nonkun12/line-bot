from datetime import datetime
import json
import os
import subprocess

CHECKPOINT_FILE = ".ai_debug_checkpoint.json"
GIT_COMMAND_TIMEOUT = float(os.environ.get("GIT_COMMAND_TIMEOUT", "10.0"))


def create_checkpoint(cwd=None):
    """
    修正適用前にGitチェックポイント情報を保存する
    """
    if cwd is None:
        cwd = os.getcwd()

    try:
        commit_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT
        )
        commit_hash = commit_proc.stdout.strip() if commit_proc.returncode == 0 else "UNKNOWN"

        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT
        )
        branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else "UNKNOWN"

        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT
        )
        modified_files = []
        if status_proc.returncode == 0:
            for line in status_proc.stdout.splitlines():
                if line.strip():
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        modified_files.append(parts[1])

        checkpoint_data = {
            "timestamp": datetime.now().isoformat(),
            "commit": commit_hash,
            "branch": branch,
            "modified_files": modified_files
        }

        filepath = os.path.join(cwd, CHECKPOINT_FILE)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)

        return {
            "ok": True,
            "message": f"チェックポイント作成完了: {commit_hash[:7]} ({branch})",
            "checkpoint": checkpoint_data
        }
    except Exception as e:
        return {
            "ok": False,
            "message": f"チェックポイント作成失敗: {e}"
        }


def restore_checkpoint(filename="app.py", cwd=None):
    """
    チェックポイント保存時の状態へ復元する
    """
    if cwd is None:
        cwd = os.getcwd()

    filepath = os.path.join(cwd, CHECKPOINT_FILE)
    backup_file = os.path.join(cwd, f"{filename}.before_auto_apply")

    restored = False
    if os.path.exists(backup_file):
        shutil_file = os.path.join(cwd, filename)
        import shutil
        shutil.copyfile(backup_file, shutil_file)
        restored = True
    else:
        try:
            proc = subprocess.run(
                ["git", "checkout", "--", filename],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=GIT_COMMAND_TIMEOUT
            )
            restored = proc.returncode == 0
        except subprocess.TimeoutExpired:
            restored = False

    remove_checkpoint(cwd=cwd)

    if restored:
        return {
            "ok": True,
            "message": f"{filename} の完全復元完了"
        }
    else:
        return {
            "ok": False,
            "message": f"{filename} の復元失敗"
        }


def remove_checkpoint(cwd=None):
    """
    チェックポイントファイルを削除する
    """
    if cwd is None:
        cwd = os.getcwd()

    filepath = os.path.join(cwd, CHECKPOINT_FILE)
    if os.path.exists(filepath):
        os.remove(filepath)
