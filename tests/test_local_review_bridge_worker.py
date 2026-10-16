import pytest

from scripts import local_review_bridge_worker as worker


BASE = "a" * 40
HEAD = "b" * 40


def payload(**changes):
    value = {
        "schema_version": 1,
        "kind": "local_code_review",
        "repository": "nonkun12/line-bot",
        "base_sha": BASE,
        "head_sha": HEAD,
    }
    value.update(changes)
    return value


@pytest.mark.parametrize("value", [
    payload(repository="attacker/other"),
    payload(base_sha="short"),
    payload(head_sha="A" * 40),
    payload(base_sha=HEAD),
    payload(extra="shell command"),
    [],
    None,
])
def test_rejects_invalid_payload(value):
    with pytest.raises(worker.WorkerError):
        worker.validate_payload(value)


def test_accepts_minimal_allowlisted_payload():
    assert worker.validate_payload(payload())["head_sha"] == HEAD


@pytest.mark.parametrize("url", [
    "http://example.com",
    "file:///tmp/test",
    "https://user:password@example.com",
    "https://example.com/path?secret=value",
])
def test_rejects_unsafe_bridge_url(url):
    with pytest.raises(worker.WorkerError):
        worker.validate_base_url(url)


def test_allows_https_and_localhost():
    assert worker.validate_base_url("https://bridge.example/api") == "https://bridge.example/api"
    assert worker.validate_base_url("http://localhost:5000") == "http://localhost:5000"


def test_dry_run_never_claims_job(monkeypatch, tmp_path, capsys):
    def should_not_request(*args, **kwargs):
        raise AssertionError("dry-run must not make network requests")

    monkeypatch.setattr(worker, "request_json", should_not_request)
    result = worker.run_once(
        "https://bridge.example", "test-key", str(tmp_path), execute=False
    )
    assert result == 0
    assert "no request made" in capsys.readouterr().out


def test_review_fetches_exact_commits_without_checkout_or_reset(monkeypatch, tmp_path):
    import subprocess

    git_calls = []
    process_calls = []

    def fake_git(repo, *args, timeout=15):
        git_calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo)
        if args == ("remote", "get-url", "origin"):
            return "https://github.com/nonkun12/line-bot.git"
        if args[:2] == ("rev-parse", "--verify"):
            return args[2].removesuffix("^{commit}")
        raise AssertionError(f"unexpected git command: {args}")

    def fake_run(args, **kwargs):
        process_calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(worker, "git", fake_git)
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    repo = worker.verify_checkout(str(tmp_path), payload())

    assert repo == tmp_path.resolve()
    assert process_calls[0][-3:] == ["origin", BASE, HEAD]
    assert process_calls[1][-3:] == ["--is-ancestor", BASE, HEAD]
    assert not any("checkout" in call or "reset" in call for call in process_calls)


def test_review_rejects_non_allowlisted_origin_before_fetch(monkeypatch, tmp_path):
    def fake_git(repo, *args, timeout=15):
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo)
        if args == ("remote", "get-url", "origin"):
            return "https://attacker.example/other.git"
        raise AssertionError("must reject origin before fetching")

    monkeypatch.setattr(worker, "git", fake_git)
    with pytest.raises(worker.WorkerError, match="origin remote"):
        worker.verify_checkout(str(tmp_path), payload())


def test_redirect_handler_never_forwards_authenticated_request():
    handler = worker._NoRedirectHandler()
    request = worker.Request("https://bridge.example/claim", headers={
        "X-Local-Review-Bridge-Key": "secret-test-value",
    })
    # urllib's default redirect handler would create a second request. This
    # worker must stop instead, so the bridge key cannot follow a redirect.
    assert handler.redirect_request(
        request, None, 302, "Found", {}, "https://attacker.example/collect"
    ) is None



def test_review_environment_does_not_include_bridge_secret(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("LOCAL_REVIEW_BRIDGE_KEY", "secret-test-value")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    env = worker._review_environment()
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"
    assert "LOCAL_REVIEW_BRIDGE_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_completion_falls_back_to_bounded_not_run_once(monkeypatch):
    calls = []
    def fake_request(url, key, method, body):
        calls.append(body)
        if len(calls) == 1:
            raise worker.WorkerError("bridge HTTP status 400")
        return {"ok": True, "status": "failed"}
    monkeypatch.setattr(worker, "request_json", fake_request)
    original = {"job_id": 12, "claim_token": "claim", "status": "REVIEWED", "report": {}}
    result = worker._completion_with_bounded_fallback(
        "https://bridge.example", "bridge-key", original, 12, "claim"
    )
    assert result["ok"] is True
    assert len(calls) == 2
    assert calls[1]["status"] == "NOT_RUN"
    assert calls[1]["job_id"] == 12



def test_trusted_script_requires_operator_pinned_digest():
    source = "print('trusted')"
    import hashlib
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    worker._verify_trusted_script(source, digest)
    with pytest.raises(worker.WorkerError, match="missing or invalid"):
        worker._verify_trusted_script(source, "")
    with pytest.raises(worker.WorkerError, match="digest mismatch"):
        worker._verify_trusted_script(source, "0" * 64)



def test_timeout_terminates_reviewer_process_group(monkeypatch):
    import signal
    import subprocess

    class FakeProcess:
        pid = 4321

        def __init__(self):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("fm", timeout)
            return ("", "")

    signals = []
    monkeypatch.setattr(worker.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    proc = FakeProcess()

    with pytest.raises(worker.WorkerError, match="timed out"):
        worker._communicate_with_timeout(proc, 10)

    assert signals == [(4321, signal.SIGTERM)]
    assert proc.calls == 2


def test_timeout_force_kills_process_group_if_graceful_stop_fails(monkeypatch):
    import signal
    import subprocess

    class FakeProcess:
        pid = 9876

        def __init__(self):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls < 3:
                raise subprocess.TimeoutExpired("fm", timeout)
            return ("", "")

    signals = []
    monkeypatch.setattr(worker.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    proc = FakeProcess()

    with pytest.raises(worker.WorkerError, match="timed out"):
        worker._communicate_with_timeout(proc, 10)

    assert signals == [(9876, signal.SIGTERM), (9876, signal.SIGKILL)]
    assert proc.calls == 3



def test_timeout_cleanup_has_bounded_wait_when_pipe_never_closes(monkeypatch):
    import signal
    import subprocess

    class FakeProcess:
        pid = 2468
        stdout = None
        stderr = None

        def __init__(self):
            self.wait_calls = 0
            self.killed = False

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired("fm", timeout)

        def wait(self, timeout=None):
            self.wait_calls += 1
            raise subprocess.TimeoutExpired("fm", timeout)

        def kill(self):
            self.killed = True

    signals = []
    monkeypatch.setattr(worker.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    proc = FakeProcess()

    with pytest.raises(worker.WorkerError, match="bounded wait"):
        worker._communicate_with_timeout(proc, 10)

    assert signals == [(2468, signal.SIGTERM), (2468, signal.SIGKILL)]
    assert proc.killed is True
    assert proc.wait_calls == 2
