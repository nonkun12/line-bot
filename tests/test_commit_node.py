import subprocess

from agents.commit.node import commit_node


def test_commit_node_skips_when_pytest_not_passed():
    state = {
        "agent_results": {},
        "test_result": {"passed": False},
    }

    result = commit_node(state)

    commit_result = result["agent_results"]["commit"]

    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True
    assert commit_result["reason"] == "pytest not passed"


def test_commit_node_skips_when_test_result_missing():
    state = {
        "agent_results": {},
    }

    result = commit_node(state)

    commit_result = result["agent_results"]["commit"]

    assert commit_result["committed"] is False
    assert commit_result["skipped"] is True


def test_commit_node_commits_when_pytest_passed(monkeypatch):
    calls = []

    def fake_run(args, cwd=None, capture_output=None, text=None):
        calls.append(args)

        class _Result:
            returncode = 0
            stdout = "deadbeef1234\n"
            stderr = ""

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    state = {
        "agent_results": {
            "fix": {"commit_message": "fix: auto generated patch"},
        },
        "test_result": {"passed": True},
    }

    result = commit_node(state)

    commit_result = result["agent_results"]["commit"]

    assert commit_result["committed"] is True
    assert commit_result["hash"] == "deadbeef1234"
    assert commit_result["message"] == "fix: auto generated patch"

    # git add / commit / rev-parse の3回呼ばれていること
    assert ["git", "add", "."] in calls
    assert ["git", "commit", "-m", "fix: auto generated patch"] in calls
    assert ["git", "rev-parse", "HEAD"] in calls


def test_commit_node_uses_default_message_when_fix_result_missing(monkeypatch):
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 0
            stdout = "cafebabe\n"
            stderr = ""

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    state = {
        "agent_results": {},
        "test_result": {"passed": True},
    }

    result = commit_node(state)

    commit_result = result["agent_results"]["commit"]

    assert commit_result["committed"] is True
    assert commit_result["message"] == "AI Debug Agent automatic fix"


def test_commit_node_reports_error_when_git_add_fails(monkeypatch):
    def fake_run(args, cwd=None, capture_output=None, text=None):
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "fatal: not a git repository"

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    state = {
        "agent_results": {},
        "test_result": {"passed": True},
    }

    result = commit_node(state)

    commit_result = result["agent_results"]["commit"]

    assert commit_result["committed"] is False
    assert "fatal" in commit_result["error"]


def test_commit_node_reports_error_when_git_commit_fails(monkeypatch):
    call_count = {"n": 0}

    def fake_run(args, cwd=None, capture_output=None, text=None):
        call_count["n"] += 1

        class _Result:
            pass

        result = _Result()

        if args == ["git", "add", "."]:
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
        elif args[:2] == ["git", "commit"]:
            result.returncode = 1
            result.stdout = ""
            result.stderr = "nothing to commit"
        else:
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""

        return result

    monkeypatch.setattr(subprocess, "run", fake_run)

    state = {
        "agent_results": {},
        "test_result": {"passed": True},
    }

    result = commit_node(state)

    commit_result = result["agent_results"]["commit"]

    assert commit_result["committed"] is False
    assert "nothing to commit" in commit_result["error"]
