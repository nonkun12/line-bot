"""
Fix Agent (agents/fix/patch_utils.py) の回帰テスト。
"""

import subprocess

from agents.fix.patch_utils import get_code_context, validate_patch


def run_git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo_with_sample_file(tmp_path):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("def foo():\n    x = data[\"key\"]\n    return x\n")
    run_git(tmp_path, "add", "sample.py")
    run_git(tmp_path, "commit", "-m", "initial")
    return sample_file


def test_get_code_context_reads_file_inside_repository(tmp_path, monkeypatch):
    sample_file = _init_repo_with_sample_file(tmp_path)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    result = get_code_context("sample.py", 2, radius=1)
    assert 'data["key"]' in result
    assert sample_file.read_text().strip() in result.strip()


def test_get_code_context_accepts_absolute_path_inside_repository(tmp_path, monkeypatch):
    sample_file = _init_repo_with_sample_file(tmp_path)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    result = get_code_context(str(sample_file), 2, radius=1)
    assert 'data["key"]' in result


def test_get_code_context_rejects_parent_path(tmp_path, monkeypatch):
    _init_repo_with_sample_file(tmp_path)
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("do not read me")
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    result = get_code_context("../secret.txt", 1)
    assert result.startswith("read error:")
    assert "do not read me" not in result


def test_get_code_context_rejects_absolute_path_outside_repository(tmp_path, monkeypatch):
    _init_repo_with_sample_file(tmp_path)
    outside = tmp_path.parent / "secret-absolute.txt"
    outside.write_text("do not read me")
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    result = get_code_context(str(outside), 1)
    assert result.startswith("read error:")
    assert "do not read me" not in result


def test_get_code_context_rejects_symlink_escape(tmp_path, monkeypatch):
    _init_repo_with_sample_file(tmp_path)
    outside_dir = tmp_path.parent / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("do not read me")
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    result = get_code_context("linked/secret.txt", 1)
    assert result.startswith("read error:")
    assert "do not read me" not in result


def test_get_code_context_rejects_invalid_line_number(tmp_path, monkeypatch):
    _init_repo_with_sample_file(tmp_path)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    assert get_code_context("sample.py", 0) == "read error: invalid line number"
    assert get_code_context("sample.py", "not-a-number") == "read error: invalid line number"


def test_validate_patch_rejects_context_line_missing_leading_space(tmp_path):
    _init_repo_with_sample_file(tmp_path)
    broken_patch = (
        "diff --git a/sample.py b/sample.py\n--- a/sample.py\n+++ b/sample.py\n"
        "@@ -1,3 +1,3 @@\n"
        "def foo():\n-    x = data[\"key\"]\n+    x = data.get(\"key\")\n     return x\n"
    )
    ok, error = validate_patch(broken_patch, repo=str(tmp_path))
    assert ok is False
    assert "corrupt patch" in error


def test_validate_patch_rejects_bare_hunk_header_without_line_numbers(tmp_path):
    _init_repo_with_sample_file(tmp_path)
    broken_patch = (
        "diff --git a/sample.py b/sample.py\n--- a/sample.py\n+++ b/sample.py\n"
        "@@\n-x = data[\"key\"]\n+x = data.get(\"key\")\n"
    )
    ok, error = validate_patch(broken_patch, repo=str(tmp_path))
    assert ok is False
    assert error != ""


def test_validate_patch_accepts_correctly_formatted_diff(tmp_path):
    _init_repo_with_sample_file(tmp_path)
    valid_patch = (
        "diff --git a/sample.py b/sample.py\n--- a/sample.py\n+++ b/sample.py\n"
        "@@ -1,3 +1,3 @@\n def foo():\n-    x = data[\"key\"]\n+    x = data.get(\"key\")\n     return x\n"
    )
    ok, error = validate_patch(valid_patch, repo=str(tmp_path))
    assert ok is True
    assert error == ""
