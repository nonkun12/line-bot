"""
Patch utility

unified diffから対象ファイルを抽出し、Fix Agent用の安全なコードコンテキストを取得する。
"""

import os
import re
import subprocess


def extract_target_files(patch: str) -> list[str]:
    """unified diffから変更対象ファイルを取得する"""
    if not patch:
        return []
    files = []
    matches = re.findall(r"\+\+\+ b/(.+)", patch)
    for file in matches:
        if file not in files:
            files.append(file)
    return files


def _resolve_repo_file(file_path: str, repo_root: str) -> str | None:
    """対象パスをリポジトリ内に限定して解決する。"""
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    root = os.path.realpath(repo_root)
    candidate = file_path.strip().replace("\\", "/")
    if "\x00" in candidate or (len(candidate) >= 2 and candidate[1] == ":"):
        return None
    if os.path.isabs(candidate):
        resolved = os.path.realpath(candidate)
    else:
        if ".." in candidate.split("/"):
            return None
        resolved = os.path.realpath(os.path.join(root, candidate))
    try:
        if os.path.commonpath([root, resolved]) != root:
            return None
    except ValueError:
        return None
    if not os.path.isfile(resolved):
        return None
    return resolved


def get_code_context(file_path: str, line: int, radius: int = 10) -> str:
    """指定ファイルのエラー行周辺コードを取得する。"""
    repo_root = os.environ.get("REPO_WORKDIR", os.getcwd())
    resolved_path = _resolve_repo_file(file_path, repo_root)
    if resolved_path is None:
        return "read error: file path is outside repository or does not exist"
    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return f"read error: {e}"
    try:
        line_number = int(line)
    except (TypeError, ValueError):
        return "read error: invalid line number"
    if line_number < 1:
        return "read error: invalid line number"
    start = max(line_number - radius - 1, 0)
    end = min(line_number + radius, len(lines))
    return "".join(lines[start:end])


def validate_patch(patch: str, repo=None):
    """git apply --checkでpatch検証する。"""
    if not patch:
        return False, "empty patch"
    if repo is None:
        repo = os.environ.get("REPO_WORKDIR", ".")
    result = subprocess.run(["git", "apply", "--check", "-"], input=patch, text=True, capture_output=True, cwd=repo)
    if result.returncode == 0:
        return True, ""
    return False, result.stderr
