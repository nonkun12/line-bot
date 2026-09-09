import subprocess

from agents.commit.node import _candidate_paths, commit_node


def _state(**overrides):
    state = {"agent_results": {}, "test_result": {"passed": True}, "patch_candidates": [{"target_file": "app.py"}]}
    state.update(overrides)
    return state


def test_commit_node_skips_when_pytest_not_passed():
    result = commit_node({"agent_results": {}, "test_result": {"passed": False}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "pytest not passed"


def test_commit_node_skips_when_test_result_missing():
    result = commit_node({"agent_results": {}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True


def test_commit_node_skips_when_passed_is_not_boolean_true():
    result = commit_node(_state(test_result={"passed": "true"}))
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "pytest not passed"


def test_candidate_paths_rejects_unsafe_paths(tmp_path):
    (tmp_path / "safe").mkdir()
    (tmp_path / "safe" / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "safe" / "module.py").write_text("", encoding="utf-8")
    state = {"patch_candidates": [
        {"target_file": "../outside.py"}, {"target_file": "/tmp/outside.py"},
        {"target_file": "C:/outside.py"}, {"target_file": "folder/../../outside.py"},
        {"target_file": "/workspace/repo/../outside.py"}, {"target_file": "."},
        {"target_file": "safe/./app.py"}, {"target_file": "safe\\module.py"},
        {"target_file": "missing.py"}, {"target_file": "safe"},
    ]}
    assert _candidate_paths(state, str(tmp_path)) == ["safe/app.py", "safe/module.py"]


def test_candidate_paths_deduplicates_targets(tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    state = {"patch_candidates": [{"target_file": "app.py"}, {"target_file": "app.py"}, {"target_file": "./app.py"}]}
    assert _candidate_paths(state, str(tmp_path)) == ["app.py"]


def test_commit_node_commits_only_safe_target_files(monkeypatch, tmp_path):
    calls = []
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    rev_parse_count = 0
    def fake_run(args, cwd=None, capture_output=None, text=None):
        nonlocal rev_parse_count
        calls.append(args)
        class _Result:
            returncode = 0
            stdout = "app.py\n"
            stderr = ""
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            rev_parse_count += 1
            _Result.stdout = "beforehead\n" if rev_parse_count == 1 else "deadbeef1234\n"
        return _Result()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    result = commit_node(_state(agent_results={"fix": {"commit_message": "fix: auto generated patch"}}))
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is True
    assert commit_result["hash"] == "deadbeef1234"
    assert commit_result["message"] == "fix: auto generated patch"
    assert ["git", "add", "--", "app.py"] in calls
    assert ["git", "diff", "--cached", "--name-only"] in calls
    assert ["git", "commit", "-m", "fix: auto generated patch"] in calls
    assert calls.count(["git", "rev-parse", "HEAD"]) == 2
    assert ["git", "add", "."] not in calls


def test_commit_node_refuses_preexisting_unrelated_staged_changes(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 0
            stdout = "unrelated.py\napp.py\n"
            stderr = ""
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            _Result.stdout = "head\n"
        return _Result()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    commit_result = commit_node(_state())["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "staged paths differ from safe patch targets"
    assert commit_result["staged_paths"] == ["app.py", "unrelated.py"]


def test_commit_node_uses_default_message_when_fix_result_missing(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    rev_parse_count = 0
    def fake_run(args, cwd=None, capture_output=None, text=None):
        nonlocal rev_parse_count
        class _Result:
            returncode = 0
            stdout = "app.py\n"
            stderr = ""
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            rev_parse_count += 1
            _Result.stdout = "cafebabe\n" if rev_parse_count == 1 else "feedface\n"
        return _Result()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    commit_result = commit_node(_state())["agent_results"]["commit"]
    assert commit_result["committed"] is True
    assert commit_result["message"] == "AI Debug Agent automatic fix"


def test_commit_node_reports_error_when_git_add_fails(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "fatal: not a git repository"
        return _Result()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    commit_result = commit_node(_state())["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert "fatal" in commit_result["error"]


def test_commit_node_reports_error_when_git_commit_fails(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 0
            stdout = "app.py\n"
            stderr = ""
        if args[:2] == ["git", "commit"]:
            _Result.returncode = 1
            _Result.stdout = ""
            _Result.stderr = "nothing to commit"
        elif args[:3] == ["git", "rev-parse", "HEAD"]:
            _Result.stdout = "head\n"
        return _Result()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    commit_result = commit_node(_state())["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert "nothing to commit" in commit_result["error"]


def test_commit_node_rejects_commit_when_head_does_not_advance(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 0
            stdout = "app.py\n"
            stderr = ""
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            _Result.stdout = "samehead\n"
        return _Result()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("REPO_WORKDIR", str(tmp_path))
    commit_result = commit_node(_state())["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["error"] == "HEAD did not advance after commit"
    assert commit_result["before_head"] == "samehead"
    assert commit_result["after_head"] == "samehead"
