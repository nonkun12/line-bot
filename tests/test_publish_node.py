import importlib.util
from pathlib import Path
from types import SimpleNamespace


_MODULE_PATH = Path(__file__).resolve().parents[1] / "standalone-agent" / "agents" / "publish" / "node.py"
_SPEC = importlib.util.spec_from_file_location("overnight_publish_node", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
node = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(node)


class FakeResponse:
    def __init__(self, status_code, data, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        return self._data


def test_publish_pushes_branch_and_creates_pr(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "nonkun12/line-bot")
    monkeypatch.setenv("AUTO_PUBLISH_JOB_BRANCH", "true")

    git_calls = []

    def fake_run_git(args, cwd):
        assert cwd == str(tmp_path)
        if args[:3] == ["remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/nonkun12/line-bot.git", stderr="")
        raise AssertionError(args)

    def fake_subprocess_run(command, cwd, capture_output, text, timeout, env):
        git_calls.append((command, cwd, env))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(node, "_run_git", fake_run_git)
    monkeypatch.setattr(node.subprocess, "run", fake_subprocess_run)

    calls = {"get": 0, "post": 0}

    def fake_get(url, **kwargs):
        calls["get"] += 1
        assert url.endswith("/repos/nonkun12/line-bot/pulls")
        assert kwargs["params"]["head"] == "nonkun12:worker/job-42"
        return FakeResponse(200, [])

    def fake_post(url, **kwargs):
        calls["post"] += 1
        assert url.endswith("/repos/nonkun12/line-bot/pulls")
        assert kwargs["json"]["head"] == "worker/job-42"
        assert kwargs["json"]["base"] == "main"
        return FakeResponse(201, {"number": 123, "html_url": "https://github.com/nonkun12/line-bot/pull/123", "state": "open"})

    monkeypatch.setattr(node.requests, "get", fake_get)
    monkeypatch.setattr(node.requests, "post", fake_post)

    result = node.publish_job_branch({
        "job_id": 42,
        "workdir": str(tmp_path),
        "commit_result": {
            "committed": True,
            "hash": "abc123",
            "message": "add feature",
            "branch": "worker/job-42",
        },
    })

    assert result["published"] is True
    assert result["branch"] == "worker/job-42"
    assert result["commit_hash"] == "abc123"
    assert result["pr"] == {
        "number": 123,
        "url": "https://github.com/nonkun12/line-bot/pull/123",
        "created": True,
        "state": "open",
    }
    assert calls == {"get": 1, "post": 1}
    assert git_calls[0][0] == ["git", "push", "origin", "HEAD:refs/heads/worker/job-42"]
    assert git_calls[0][2]["GIT_HTTP_EXTRAHEADER"] == "Authorization: Bearer test-token"


def test_publish_reuses_existing_open_pr(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "nonkun12/line-bot")
    monkeypatch.setenv("AUTO_PUBLISH_JOB_BRANCH", "true")

    monkeypatch.setattr(
        node,
        "_run_git",
        lambda args, cwd: SimpleNamespace(
            returncode=0,
            stdout="https://github.com/nonkun12/line-bot.git" if args[:3] == ["remote", "get-url", "origin"] else "",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        node.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        node.requests,
        "get",
        lambda url, **kwargs: FakeResponse(
            200,
            [{"number": 456, "html_url": "https://github.com/nonkun12/line-bot/pull/456", "state": "open"}],
        ),
    )

    def fail_post(*args, **kwargs):
        raise AssertionError("POST must not be called when an open PR already exists")

    monkeypatch.setattr(node.requests, "post", fail_post)

    result = node.publish_job_branch({
        "job_id": 43,
        "workdir": str(tmp_path),
        "commit_result": {"committed": True, "hash": "def456", "message": "fix"},
    })

    assert result["published"] is True
    assert result["branch"] == "worker/job-43"
    assert result["pr"] == {
        "number": 456,
        "url": "https://github.com/nonkun12/line-bot/pull/456",
        "created": False,
        "state": "open",
    }


def test_publish_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_PUBLISH_JOB_BRANCH", raising=False)
    result = node.publish_job_branch({
        "job_id": 44,
        "commit_result": {"committed": True, "branch": "worker/job-44", "hash": "abc"},
    })
    assert result["published"] is False
    assert result["manual_required"] is True
    assert result["branch"] == "worker/job-44"


def test_publish_requires_commit_success(monkeypatch):
    result = node.publish_job_branch({"job_id": 45, "commit_result": {"committed": False}})
    assert result == {"published": False, "skipped": True, "reason": "commit not completed"}
