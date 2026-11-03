import json

import scripts.goal_job_remote_worker as worker


def test_api_claim_sends_internal_authentication(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok": true, "claimed": false}'

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.get_header("X-internal-key")
        captured["body"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(worker, "INTERNAL_KEY", "secret")
    monkeypatch.setattr(worker.urllib.request, "urlopen", open_request)
    result = worker._api("/internal/goal-jobs/claim", {})
    assert result == {"ok": True, "claimed": False}
    assert captured["url"].endswith("/internal/goal-jobs/claim")
    assert captured["key"] == "secret"
    assert captured["body"] == {}


def test_api_fails_closed_without_internal_key(monkeypatch):
    monkeypatch.setattr(worker, "INTERNAL_KEY", "")
    try:
        worker._api("/internal/goal-jobs/claim", {})
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("missing internal key must fail closed")


def test_workflow_run_waits_for_exact_sha_and_success(monkeypatch):
    calls = []
    outputs = [
        "",
        json.dumps([
            {"databaseId": 1, "url": "wrong", "status": "completed", "conclusion": "success", "headSha": "b" * 40},
            {"databaseId": 2, "url": "right", "status": "completed", "conclusion": "success", "headSha": "a" * 40},
        ]),
    ]

    def run(*args, **kwargs):
        calls.append(args)
        return outputs.pop(0)

    monkeypatch.setattr(worker, "_run", run)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)
    result = worker._workflow_run("pytest.yml", "line-dev/1", "a" * 40)
    assert result == {"id": 2, "url": "right", "success": True}
    assert calls[0][:3] == ("gh", "workflow", "run")
