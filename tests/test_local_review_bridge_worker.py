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


def test_checkout_requires_exact_head_sha(monkeypatch, tmp_path):
    calls = []

    def fake_git(repo, *args, timeout=15):
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo)
        if args == ("rev-parse", "HEAD"):
            return "c" * 40
        raise AssertionError("must stop after mismatched HEAD")

    monkeypatch.setattr(worker, "git", fake_git)
    with pytest.raises(worker.WorkerError, match="does not exactly match"):
        worker.verify_checkout(str(tmp_path), payload())
    assert len(calls) == 2


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
