import subprocess

from agents.patch.apply import apply_patch


VALID_PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print("before")
+print("after")
"""


def run_git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def test_apply_patch_on_temporary_git_repo(tmp_path):
    # 本物のline-botリポジトリではなく、tmp_path内だけでGitリポジトリを作る
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")

    app_file = tmp_path / "app.py"
    app_file.write_text('print("before")\n')

    run_git(tmp_path, "add", "app.py")
    run_git(tmp_path, "commit", "-m", "initial")

    result = apply_patch(VALID_PATCH, str(tmp_path))

    assert result["applied"] is True
    assert result["branch"].startswith("fix/auto-")
    assert result["error"] is None

    assert app_file.read_text() == 'print("after")\n'

    branch = run_git(
        tmp_path,
        "rev-parse",
        "--abbrev-ref",
        "HEAD",
    ).stdout.strip()

    assert branch == result["branch"]
