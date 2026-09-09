import subprocess

from agents.patch.apply import apply_patch


VALID_PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print("before")
+print("after")
"""
INVALID_PATCH_AFTER_CHECK = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-print("unexpected")
+print("after")
"""


def run_git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_apply_patch_on_temporary_git_repo(tmp_path):
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
    branch = run_git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert branch == result["branch"]


def test_apply_patch_rejects_dirty_worktree_before_branch_creation(tmp_path):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    app_file = tmp_path / "app.py"
    app_file.write_text('print("before")\n')
    run_git(tmp_path, "add", "app.py")
    run_git(tmp_path, "commit", "-m", "initial")
    app_file.write_text('print("user change")\n')
    result = apply_patch(VALID_PATCH, str(tmp_path))
    assert result["applied"] is False
    assert result["branch"] is None
    assert "dirty working tree" in result["error"]
    assert app_file.read_text() == 'print("user change")\n'
    current_branch = run_git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert current_branch == "master" or current_branch == "main"
    branches = run_git(tmp_path, "branch", "--format=%(refname:short)").stdout.splitlines()
    assert not any(branch.startswith("fix/auto-") for branch in branches)


def test_apply_patch_rolls_back_temporary_branch_when_apply_fails(tmp_path):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    app_file = tmp_path / "app.py"
    app_file.write_text('print("before")\n')
    run_git(tmp_path, "add", "app.py")
    run_git(tmp_path, "commit", "-m", "initial")
    original_run = subprocess.run
    def fake_run(args, cwd=None, capture_output=None, text=None, check=False):
        if args[:3] == ["git", "checkout", "-b"]:
            result = original_run(args, cwd=cwd, capture_output=capture_output, text=text, check=check)
            app_file.write_text('print("changed externally")\n')
            return result
        return original_run(args, cwd=cwd, capture_output=capture_output, text=text, check=check)
    import agents.patch.apply as patch_apply_module
    original_module_run = patch_apply_module.subprocess.run
    patch_apply_module.subprocess.run = fake_run
    try:
        result = apply_patch(VALID_PATCH, str(tmp_path))
    finally:
        patch_apply_module.subprocess.run = original_module_run
    assert result["applied"] is False
    assert result["branch"] is None
    assert "patch apply failed" in result["error"]
    assert app_file.read_text() == 'print("changed externally")\n'
    current_branch = run_git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert current_branch == "master" or current_branch == "main"
    branches = run_git(tmp_path, "branch", "--format=%(refname:short)").stdout.splitlines()
    assert not any(branch.startswith("fix/auto-") for branch in branches)
