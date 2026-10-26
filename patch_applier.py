import os
import re
import shutil
import subprocess
from git_safety import create_checkpoint, restore_checkpoint, remove_checkpoint


def _patch_targets_only_requested_file(patch, filename):
    """Reject multi-file, absolute, and traversal paths before invoking git apply."""
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        return False

    headers = []
    for line in patch.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            kind = line[:3]
            path = line[4:].split("\t", 1)[0].strip()
            if path in {"/dev/null", "dev/null"}:
                headers.append((kind, path))
                continue
            if path.startswith(("a/", "b/")):
                path = path[2:]
            headers.append((kind, path))

    if len(headers) != 2:
        return False
    old_header, new_header = headers
    if old_header[0] != "---" or new_header[0] != "+++":
        return False
    return old_header[1] == filename and new_header[1] in {filename, f"{filename}.fixed"}


def check_patch(patch, filename="app.py"):
    """
    git apply --check で事前にパッチ適用可能性を検証する
    """
    if not patch or not patch.strip() or not patch.startswith("--- "):
        return {
            "ok": False,
            "message": "無効なパッチ形式です"
        }

    if not _patch_targets_only_requested_file(patch, filename):
        return {
            "ok": False,
            "message": "パッチの変更対象が許可された単一ファイルと一致しません"
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
            capture_output=True
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
            capture_output=True
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
