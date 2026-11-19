"""
Fix Agent (agents/fix/patch_utils.py) の validate_patch() に対する回帰テスト。

背景:
Fix Agentが生成するunified diffが、git applyから
「corrupt patch at line N」として拒否される不具合があった。

原因は、agents/fix/node.py の _SYSTEM_PROMPT に埋め込まれていた
unified diffのサンプルが、以下の点で実際には不正な形式だったこと:
- ハンクヘッダーが行番号なしの裸の "@@" になっていた
  (正しくは "@@ -開始行,行数 +開始行,行数 @@")
- 変更しないcontext行(先頭に半角スペース1つが必要)の例が
  一切示されていなかった

このテストは、上記の不正パターン(特にcontext行の先頭スペース欠落)を
実際にgit applyへ渡した際に、validate_patch()が
「corrupt patch」を含むエラーとして正しく検出できることを保証する。
"""

import subprocess

from agents.fix.patch_utils import validate_patch


def run_git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo_with_sample_file(tmp_path):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")

    sample_file = tmp_path / "sample.py"
    sample_file.write_text(
        "def foo():\n"
        "    x = data[\"key\"]\n"
        "    return x\n"
    )

    run_git(tmp_path, "add", "sample.py")
    run_git(tmp_path, "commit", "-m", "initial")

    return sample_file


def test_validate_patch_rejects_context_line_missing_leading_space(tmp_path):
    """
    context行(変更しない行)の先頭に半角スペースが無いpatchは、
    git apply --check により「corrupt patch」として拒否されることを確認する。

    これは旧システムプロンプトのサンプルが再生産していた、
    実際に報告された不具合パターンそのものの再現テスト。
    """

    _init_repo_with_sample_file(tmp_path)

    # context行 "def foo():" の先頭に本来必要なスペースが無い不正なdiff
    broken_patch = (
        "diff --git a/sample.py b/sample.py\n"
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,3 +1,3 @@\n"
        "def foo():\n"
        "-    x = data[\"key\"]\n"
        "+    x = data.get(\"key\")\n"
        "     return x\n"
    )

    ok, error = validate_patch(broken_patch, repo=str(tmp_path))

    assert ok is False
    assert "corrupt patch" in error


def test_validate_patch_rejects_bare_hunk_header_without_line_numbers(tmp_path):
    """
    旧システムプロンプトのサンプルと同じ、行番号の無い裸の "@@" ヘッダーと
    context行を含まないpatchが、git apply --checkで拒否されることを確認する。
    """

    _init_repo_with_sample_file(tmp_path)

    broken_patch = (
        "diff --git a/sample.py b/sample.py\n"
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@\n"
        "- x = data[\"key\"]\n"
        "+ x = data.get(\"key\")\n"
    )

    ok, error = validate_patch(broken_patch, repo=str(tmp_path))

    assert ok is False
    assert error != ""


def test_validate_patch_accepts_correctly_formatted_diff(tmp_path):
    """
    正しいハンクヘッダー(行番号付き)と、先頭に半角スペースを持つ
    context行を含む、正しい形式のunified diffは検証を通過することを確認する。

    corrupt patch対策の修正が、正常なdiffまで壊していないことの
    サニティチェックを兼ねる。
    """

    _init_repo_with_sample_file(tmp_path)

    valid_patch = (
        "diff --git a/sample.py b/sample.py\n"
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def foo():\n"
        "-    x = data[\"key\"]\n"
        "+    x = data.get(\"key\")\n"
        "     return x\n"
    )

    ok, error = validate_patch(valid_patch, repo=str(tmp_path))

    assert ok is True
    assert error == ""
