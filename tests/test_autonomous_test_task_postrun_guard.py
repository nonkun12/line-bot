from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.autonomous_task_target_allowlist import TARGETS
from scripts.autonomous_test_task_postrun_guard import (
    verify_append_only_test_change,
    verify_policy_run,
)


def test_accepts_exactly_one_appended_test_function():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new_boundary():\n    assert target(0) == 0\n"
    assert verify_append_only_test_change(before, after) == "test_new_boundary"


def test_rejects_modification_of_existing_test():
    before = "def test_existing():\n    assert True\n"
    after = "def test_existing():\n    assert False\n\n\ndef test_new():\n    assert True\n"
    with pytest.raises(ValueError, match="existing_test_file_ast_was_modified"):
        verify_append_only_test_change(before, after)


def test_rejects_removal_of_existing_test():
    before = "def test_existing():\n    assert True\n"
    after = "def test_new():\n    assert True\n"
    with pytest.raises(ValueError, match="change_must_append_exactly_one"):
        verify_append_only_test_change(before, after)


def test_rejects_non_test_top_level_append():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\nVALUE = 1\n"
    with pytest.raises(ValueError, match="appended_node_is_not"):
        verify_append_only_test_change(before, after)


def test_rejects_network_or_process_api_in_new_test():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new():\n    subprocess.run(['echo', 'bad'])\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden"):
        verify_append_only_test_change(before, after)


def test_rejects_import_inside_new_test():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new():\n    import socket\n"
    with pytest.raises(ValueError, match="new_test_must_not_add_imports"):
        verify_append_only_test_change(before, after)


def test_rejects_pathlib_filesystem_mutation():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new(tmp_path):\n    tmp_path.joinpath('x').unlink(missing_ok=True)\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden_attribute"):
        verify_append_only_test_change(before, after)


def test_rejects_dynamic_attribute_escape_hatch():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new():\n    getattr(__builtins__, 'eval')('1 + 1')\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden_escape_hatch|new_test_uses_forbidden_attribute"):
        verify_append_only_test_change(before, after)


def test_rejects_os_rename_even_without_direct_os_root_check():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new():\n    os.rename('a', 'b')\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden_attribute|new_test_uses_forbidden_os_api"):
        verify_append_only_test_change(before, after)



def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _policy_git_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    target = TARGETS[0][1]
    path = repo / target
    path.parent.mkdir(parents=True, exist_ok=True)
    before = "def test_existing():\n    assert True\n"
    path.write_text(before, encoding="utf-8")
    _git(repo, "add", target)
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    path.write_text(before + "\n\ndef test_added():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", target)
    _git(repo, "commit", "-m", "append test")
    produced = _git(repo, "rev-parse", "HEAD")
    policy = {
        "status": "POLICY_ADMITTED",
        "admitted_task_id": "task-1",
        "admitted_allowed_path": target,
    }
    rows = [{
        "task_id": "task-1",
        "status": "PASS",
        "exit_code": 0,
        "base_sha": base,
        "produced_sha": produced,
    }]
    return repo, target, base, produced, policy, rows


def test_policy_run_requires_produced_commit_to_be_checked_out_head(tmp_path):
    repo, target, base, produced, policy, rows = _policy_git_repo(tmp_path)
    _git(repo, "checkout", "--detach", base)
    with pytest.raises(ValueError, match="produced_sha_is_not_checked_out_head"):
        verify_policy_run(policy, rows, repo, base)


def test_policy_run_rejects_uncommitted_or_untracked_changes(tmp_path):
    repo, target, base, produced, policy, rows = _policy_git_repo(tmp_path)
    (repo / "unexpected.txt").write_text("untracked", encoding="utf-8")
    with pytest.raises(ValueError, match="worktree_not_clean_after_commit"):
        verify_policy_run(policy, rows, repo, base)


def test_policy_run_accepts_exact_clean_sha_bound_append(tmp_path):
    repo, target, base, produced, policy, rows = _policy_git_repo(tmp_path)
    result = verify_policy_run(policy, rows, repo, base)
    assert result["status"] == "POLICY_GUARD_PASS"
    assert result["test_function"] == "test_added"


def test_policy_run_allows_only_known_workflow_diagnostic_artifacts(tmp_path):
    repo, target, base, produced, policy, rows = _policy_git_repo(tmp_path)
    diagnostic = repo / "artifacts" / "maintenance-ai" / "diagnosis.json"
    diagnostic.parent.mkdir(parents=True)
    diagnostic.write_text("{}\\n", encoding="utf-8")
    result = verify_policy_run(policy, rows, repo, base)
    assert result["status"] == "POLICY_GUARD_PASS"
