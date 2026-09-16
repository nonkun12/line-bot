import subprocess

from agents.commit.node import commit_node


SAFE_CANDIDATE = {"patch_candidates": [{"target_file": "agents/fix/node.py"}]}


def test_commit_node_skips_when_pytest_not_passed():
    state = {"agent_results": {}, "test_result": {"passed": False}}
    result = commit_node(state)
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "pytest not passed"


def test_commit_node_skips_when_test_result_missing():
    result = commit_node({"agent_results": {}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True


def test_commit_node_commits_only_safe_patch_targets(monkeypatch):
    calls = []
    diff_calls = 0

    def fake_run(args, cwd=None, capture_output=None, text=None):
        nonlocal diff_calls
        calls.append(args)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = _Result()
        if args[1] == "branch":
            result.stdout = "work/fix-management\n"
        elif args[1] == "diff":
            diff_calls += 1
            result.stdout = "" if diff_calls == 1 else "agents/fix/node.py\n"
        elif args[1] == "rev-parse":
            result.stdout = "deadbeef1234\n"
        elif args[1] == "diff-tree":
            result.stdout = "agents/fix/node.py\n"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    state = {
        **SAFE_CANDIDATE,
        "agent_results": {"fix": {"commit_message": "fix: auto generated patch"}},
        "test_result": {"passed": True},
    }
    result = commit_node(state)
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is True
    assert commit_result["hash"] == "deadbeef1234"
    assert commit_result["message"] == "fix: auto generated patch"
    assert commit_result["paths"] == ["agents/fix/node.py"]
    assert commit_result["branch"] == "work/fix-management"
    assert commit_result["verification"] is True
    assert ["git", "add", "--", "agents/fix/node.py"] in calls
    assert ["git", "add", "."] not in calls
    assert ["git", "commit", "-m", "fix: auto generated patch"] in calls
    assert ["git", "rev-parse", "HEAD"] in calls
    assert ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"] in calls


def test_commit_node_uses_default_message_when_fix_result_missing(monkeypatch):
    diff_calls = 0

    def fake_run(args, cwd=None, capture_output=None, text=None):
        nonlocal diff_calls

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = _Result()
        if args[1] == "branch":
            result.stdout = "work/test\n"
        elif args[1] == "diff":
            diff_calls += 1
            result.stdout = "" if diff_calls == 1 else "agents/fix/node.py\n"
        elif args[1] == "rev-parse":
            result.stdout = "cafebabe\n"
        elif args[1] == "diff-tree":
            result.stdout = "agents/fix/node.py\n"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = commit_node({**SAFE_CANDIDATE, "agent_results": {}, "test_result": {"passed": True}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is True
    assert commit_result["message"] == "AI Debug Agent automatic fix"


def test_commit_node_skips_without_safe_patch_targets(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("git must not run without a safe patch target")

    monkeypatch.setattr(subprocess, "run", fail_run)
    result = commit_node({"agent_results": {}, "test_result": {"passed": True}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "no safe patch target files"


def test_commit_node_refuses_direct_commit_on_main(monkeypatch):
    calls = []

    def fake_run(args, cwd=None, capture_output=None, text=None):
        calls.append(args)

        class _Result:
            returncode = 0
            stdout = "main\n"
            stderr = ""

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = commit_node({**SAFE_CANDIDATE, "test_result": {"passed": True}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert "direct commit forbidden" in commit_result["reason"]
    assert ["git", "branch", "--show-current"] in calls
    assert not any(call[:2] == ["git", "commit"] for call in calls)


def test_commit_node_refuses_preexisting_staged_changes(monkeypatch):
    calls = []

    def fake_run(args, cwd=None, capture_output=None, text=None):
        calls.append(args)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = _Result()
        if args[1] == "branch":
            result.stdout = "work/test\n"
        elif args[1] == "diff":
            result.stdout = "other.py\n"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = commit_node({**SAFE_CANDIDATE, "test_result": {"passed": True}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "pre-existing staged changes detected"
    assert commit_result["staged_paths"] == ["other.py"]
    assert not any(call[:2] == ["git", "add"] for call in calls)


def test_commit_node_reports_error_when_git_add_fails(monkeypatch):
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = _Result()
        if args[1] == "branch":
            result.stdout = "work/test\n"
        elif args[1] == "add":
            result.returncode = 1
            result.stderr = "fatal: not a git repository"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = commit_node({**SAFE_CANDIDATE, "test_result": {"passed": True}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert "fatal" in commit_result["error"]
    assert commit_result["paths"] == ["agents/fix/node.py"]


def test_commit_node_reports_error_when_git_commit_fails(monkeypatch):
    diff_calls = 0

    def fake_run(args, cwd=None, capture_output=None, text=None):
        nonlocal diff_calls

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = _Result()
        if args[1] == "branch":
            result.stdout = "work/test\n"
        elif args[1] == "diff":
            diff_calls += 1
            result.stdout = "" if diff_calls == 1 else "agents/fix/node.py\n"
        elif args[1] == "commit":
            result.returncode = 1
            result.stderr = "nothing to commit"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = commit_node({**SAFE_CANDIDATE, "agent_results": {}, "test_result": {"passed": True}})
    commit_result = result["agent_results"]["commit"]
    assert commit_result["committed"] is False
    assert "nothing to commit" in commit_result["error"]
