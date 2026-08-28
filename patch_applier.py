import os
import shutil
import subprocess
from git_safety import create_checkpoint, restore_checkpoint, remove_checkpoint

GIT_COMMAND_TIMEOUT = float(os.environ.get("GIT_COMMAND_TIMEOUT", "10.0"))


def check_patch(patch, filename="app.py"):
    """
    git apply --check で事前にパッチ適用可能性を検証する
    """
    if not patch or not patch.strip() or not patch.startswith("--- "):
        return {
            "ok": False,
            "message": "無効なパッチ形式です"
        }

    if not os.path.exists(filename):
        return {
            "ok": False,
            "message": f"対象ファイルが存在しません: {filename}"
        }

    try:
        check_proc = subprocess.run(
            ["git", "apply", "--check", "--ignore-space-change", "--ignore-whitespace"],
            input=patch,
            text=True,
            capture_output=True,
            timeout=GIT_COMMAND_TIMEOUT,
        )

        if check_proc.returncode == 0:
            return {
                "ok": True,
                "message": "git apply --check 成功"
            }
        else:
            return {
                "ok": False,
                "message": f"git apply --check 失敗: {check_proc.stderr.strip()}"
            }
    except Exception as e:
        return {
            "ok": False,
            "message": f"検証中エラー: {e}"
        }


def apply_patch(patch, filename="app.py"):
    """
    unified diff形式のパッチを安全に適用する
    1. 事前検証 (git apply --check)
    2. Gitチェックポイント作成 & 適用前バックアップ作成
    3. パッチ適用 (git apply)
    4. 失敗時自動ロールバック
    """
    check_res = check_patch(patch, filename=filename)
    if not check_res["ok"]:
        return check_res

    # Git チェックポイント保存
    create_checkpoint()

    backup_file = f"{filename}.before_auto_apply"
    shutil.copyfile(filename, backup_file)

    try:
        proc = subprocess.run(
            ["git", "apply", "--ignore-space-change", "--ignore-whitespace"],
            input=patch,
            text=True,
            capture_output=True,
            timeout=GIT_COMMAND_TIMEOUT,
        )

        if proc.returncode == 0:
            return {
                "ok": True,
                "message": f"パッチ適用完了 (バックアップ: {backup_file})"
            }

        # 適用失敗時のロールバック
        restore_checkpoint(filename=filename)
        return {
            "ok": False,
            "message": f"パッチ適用失敗 (ロールバック完了): {proc.stderr.strip()}"
        }

    except Exception as e:
        restore_checkpoint(filename=filename)
        return {
            "ok": False,
            "message": f"パッチ適用処理エラー (ロールバック完了): {e}"
        }
