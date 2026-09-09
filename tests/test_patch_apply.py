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


def test_apply_patch_rolls_back_temporary_branch_when_apply_fails(tmp_path, monkeypatch):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    app_file = tmp_path / "app.py"
    app_file.write_text('print("before")\n')
    run_git(tmp_path, "add", "app.py")
    run_git(tmp_path, "commit", "-m", "initial")

    import agents.patch.apply as patch_apply_module

    original_run_git = patch_apply_module._run_git

    def fail_apply(args, cwd):
        if args and args[0] == "apply" and "--check" not in args:
            return subprocess.CompletedProcess(
                ["git", *args], returncode=1, stdout="", stderr="simulated apply failure"
            )
        return original_run_git(args, cwd)

    monkeypatch.setattr(patch_apply_module, "_run_git", fail_apply)
    result = apply_patch(VALID_PATCH, str(tmp_path))

    assert result["applied"] is False
    assert result["branch"] is None
    assert "patch apply failed" in result["error"]
    assert app_file.read_text() == 'print("before")\n'
    current_branch = run_git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert current_branch == "master" or current_branch == "main"
    branches = run_git(tmp_path, "branch", "--format=%(refname:short)").stdout.splitlines()
    assert not any(branch.startswith("fix/auto-") for branch in branches)
