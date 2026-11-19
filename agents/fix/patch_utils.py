"""
Patch utility

unified diffから対象ファイルを抽出する。
"""

import re


def extract_target_files(patch: str) -> list[str]:
    """
    unified diffから変更対象ファイルを取得する
    """

    if not patch:
        return []

    files = []

    matches = re.findall(
        r"\+\+\+ b/(.+)",
        patch
    )

    for file in matches:
        if file not in files:
            files.append(file)

    return files


def get_code_context(
    file_path: str,
    line: int,
    radius: int = 10,
) -> str:
    """
    指定ファイルのエラー行周辺コードを取得する
    """

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:
            lines = f.readlines()

    except Exception as e:
        return f"read error: {e}"


    start = max(
        line - radius - 1,
        0
    )

    end = min(
        line + radius,
        len(lines)
    )


    result = []

    for i in range(start, end):
        result.append(
            lines[i]
        )


    return "".join(result)


import subprocess


def validate_patch(patch: str, repo="."):
    """
    git apply --checkでpatch検証
    """

    if not patch:
        return False, "empty patch"

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
        cwd=repo,
    )

    if result.returncode == 0:
        return True, ""

    return False, result.stderr


import subprocess


def validate_patch(patch: str, repo="."):
    """
    git apply --checkでpatch検証
    """

    if not patch:
        return False, "empty patch"

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
        cwd=repo,
    )

    if result.returncode == 0:
        return True, ""

    return False, result.stderr
