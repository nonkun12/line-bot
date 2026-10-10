import json
from unittest.mock import patch

import httpx
import pytest

import obsidian_loop_dispatch as dispatch
import routes.obsidian_bridge as obsidian_routes
from scripts import line_development_worker_v2 as worker
from scripts.run_minimal_autonomous_loop import incident_tasks


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.github.com/test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("fake error", request=request, response=response)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, runs=None, dispatch_status=204, runs_status=200):
        self.runs = runs if runs is not None else []
        self.dispatch_status = dispatch_status
        self.runs_status = runs_status
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return FakeResponse(self.runs_status, {"workflow_runs": self.runs})

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return FakeResponse(self.dispatch_status, {})


@pytest.mark.parametrize(
    ("token", "repo", "expected"),
    [
        ("test-only-secret", "nonkun12/line-bot", {
            "token_present": True, "repo_format_valid": True, "repo_is_target": True
        }),
        ("", "nonkun12/line-bot", {
            "token_present": False, "repo_format_valid": True, "repo_is_target": True
        }),
        ("test-only-secret", "malformed//repo", {
            "token_present": True, "repo_format_valid": False, "repo_is_target": False
        }),
    ],
)
def test_dispatch_configuration_status_exposes_only_safe_booleans(monkeypatch, token, repo, expected):
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", token)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("AI_REPORT_GITHUB_REPO", repo)
    actual = dispatch.dispatch_configuration_status()
    assert actual == expected
    assert all(isinstance(value, bool) for value in actual.values())
    assert token not in json.dumps(actual) if token else True


def test_dispatch_rejects_unapproved_categories_and_details(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "dummy-token")
    assert dispatch.request_obsidian_incident_repair("local_job_rejected", "PermissionError", 1) == (
        False, "incident_not_eligible"
    )
    assert dispatch.request_obsidian_incident_repair("vault_write_failed", "raw note text", 1) == (
        False, "incident_not_eligible"
    )


def test_dispatch_fails_closed_when_token_is_missing(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS_DISPATCH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert dispatch.request_obsidian_incident_repair("local_job_failed", "RuntimeError", 1) == (
        False, "dispatch_token_missing"
    )


def test_dispatch_sends_only_allowlisted_metadata(monkeypatch):
    monkeypatch.setenv("AI_REPORT_GITHUB_REPO", "nonkun12/line-bot")
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "dummy-token")
    monkeypatch.setattr(dispatch, "_LAST_DISPATCH_AT", {})
    fake = FakeClient()
    with patch.object(dispatch.httpx, "Client", return_value=fake):
        ok, reason = dispatch.request_obsidian_incident_repair("local_job_failed", "RuntimeError", 17)
    assert (ok, reason) == (True, "dispatch_accepted")
    post_call = next(call for call in fake.calls if call[0] == "post")
    body = post_call[2]["json"]
    assert body == {
        "ref": "main",
        "inputs": {
            "max_tasks": "2",
            "mode": "obsidian_incident",
            "incident_category": "local_job_failed",
            "incident_detail": "RuntimeError",
            "incident_job_id": "17",
        },
    }
    assert "vault" not in json.dumps(body).lower()
    assert "dummy-token" not in json.dumps(body)




@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [(401, "github_http_401"), (403, "github_http_403"), (404, "github_http_404")],
)
def test_dispatch_returns_safe_github_http_status(monkeypatch, status_code, expected_reason):
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "dummy-token")
    monkeypatch.setattr(dispatch, "_LAST_DISPATCH_AT", {})
    fake = FakeClient(runs_status=status_code)
    with patch.object(dispatch.httpx, "Client", return_value=fake):
        ok, reason = dispatch.request_obsidian_incident_repair(
            "local_job_failed", "RuntimeError", 17
        )
    assert (ok, reason) == (False, expected_reason)
    assert not any(call[0] == "post" for call in fake.calls)


def test_dispatch_skips_when_loop_is_already_running(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "dummy-token")
    monkeypatch.setattr(dispatch, "_LAST_DISPATCH_AT", {})
    fake = FakeClient(runs=[{"status": "in_progress"}])
    with patch.object(dispatch.httpx, "Client", return_value=fake):
        ok, reason = dispatch.request_obsidian_incident_repair("vault_write_failed", "PermissionError", 4)
    assert (ok, reason) == (False, "loop_already_running")
    assert not any(call[0] == "post" for call in fake.calls)


def test_dispatch_cooldown_prevents_repeated_hosted_runs(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS_DISPATCH_TOKEN", "dummy-token")
    monkeypatch.setattr(dispatch, "_LAST_DISPATCH_AT", {"vault_write_failed": dispatch.time.monotonic()})
    fake = FakeClient()
    with patch.object(dispatch.httpx, "Client", return_value=fake):
        ok, reason = dispatch.request_obsidian_incident_repair("vault_write_failed", "PermissionError", 4)
    assert (ok, reason) == (False, "cooldown_active")
    assert not fake.calls


def test_worker_strictly_filters_files_to_task_manifest(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv(
        "AUTONOMOUS_ALLOWED_PATHS",
        json.dumps(["tests/test_obsidian_mac_bridge.py"]),
    )
    monkeypatch.setattr(
        worker,
        "run",
        lambda _cmd: SimpleNamespace(
            returncode=0,
            stdout="tests/test_obsidian_mac_bridge.py\ntests/test_management_router.py\n",
            stderr="",
        ),
    )
    assert worker.repo_files() == ["tests/test_obsidian_mac_bridge.py"]


@pytest.mark.parametrize("manifest", [
    "{not json",
    "[]",
    '["../config.py"]',
    '["/tmp/vault.md"]',
    '[".github/workflows/distributed-autonomous-loop.yml"]',
    '["tests/test_obsidian_mac_bridge.py\\nmalicious"]',
])
def test_worker_rejects_invalid_or_protected_task_manifest(monkeypatch, manifest):
    from types import SimpleNamespace

    monkeypatch.setenv("AUTONOMOUS_ALLOWED_PATHS", manifest)
    monkeypatch.setattr(
        worker,
        "run",
        lambda _cmd: SimpleNamespace(
            returncode=0,
            stdout="tests/test_obsidian_mac_bridge.py\n",
            stderr="",
        ),
    )
    with pytest.raises(RuntimeError, match="AUTONOMOUS_ALLOWED_PATHS"):
        worker.repo_files()


def test_incident_runner_builds_two_path_scoped_tasks():
    tasks = incident_tasks("vault_write_failed", "PermissionError", "17")
    assert len(tasks) == 2
    assert tasks[0]["id"] == "obsidian-bridge-fix-vault_write_failed-permissionerror"
    assert tasks[1]["id"] == "obsidian-bridge-regression-vault_write_failed-permissionerror"
    assert "job_id=17" in tasks[0]["instruction"]
    assert tasks[0]["allowed_paths"]
    assert all(path.startswith(("core/obsidian", "obsidian_loop", "routes/obsidian", "scripts/obsidian")) for path in tasks[0]["allowed_paths"])
    assert all(path.startswith("tests/") for path in tasks[1]["allowed_paths"])


def test_incident_runner_rejects_arbitrary_text():
    with pytest.raises(ValueError):
        incident_tasks("vault_write_failed", "raw message with secret", "17")
    with pytest.raises(ValueError):
        incident_tasks("local_job_failed", "RuntimeError", "../17")


def test_complete_route_dispatches_only_failed_repairable_incidents(monkeypatch):
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(obsidian_routes.obsidian_bridge_bp)
    app.config.update(TESTING=True)
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "dummy-bridge-key")
    monkeypatch.setattr(obsidian_routes, "get_job", lambda _job_id: {
        "id": 17, "job_type": "obsidian", "status": "running", "user_id": "dummy-user"
    })
    monkeypatch.setattr(obsidian_routes, "complete_claimed_job", lambda *args, **kwargs: True)
    dispatch_calls = []
    monkeypatch.setattr(
        obsidian_routes,
        "request_obsidian_incident_repair",
        lambda category, detail, job_id: (dispatch_calls.append((category, detail, job_id)) or True, "dispatch_accepted"),
    )
    client = app.test_client()
    response = client.post(
        "/api/obsidian/complete",
        headers={"X-Obsidian-Bridge-Key": "dummy-bridge-key"},
        json={
            "job_id": 17,
            "claim_token": "dummy-claim-token",
            "success": False,
            "reply": None,
            "error": "local operation failed (RuntimeError)",
            "diagnostic_category": "local_job_failed",
            "diagnostic_detail": "RuntimeError",
        },
    )
    assert response.status_code == 200
    assert dispatch_calls == [("local_job_failed", "RuntimeError", 17)]


def test_complete_route_does_not_dispatch_for_normal_rejections(monkeypatch):
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(obsidian_routes.obsidian_bridge_bp)
    app.config.update(TESTING=True)
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "dummy-bridge-key")
    monkeypatch.setattr(obsidian_routes, "get_job", lambda _job_id: {
        "id": 17, "job_type": "obsidian", "status": "running", "user_id": "dummy-user"
    })
    monkeypatch.setattr(obsidian_routes, "complete_claimed_job", lambda *args, **kwargs: True)
    dispatch_calls = []
    monkeypatch.setattr(
        obsidian_routes,
        "request_obsidian_incident_repair",
        lambda *args, **kwargs: (dispatch_calls.append(args) or True, "dispatch_accepted"),
    )
    response = app.test_client().post(
        "/api/obsidian/complete",
        headers={"X-Obsidian-Bridge-Key": "dummy-bridge-key"},
        json={
            "job_id": 17, "claim_token": "dummy-claim-token",
            "success": False, "reply": None, "error": "blocked",
            "diagnostic_category": "local_job_rejected",
            "diagnostic_detail": "overwrite_blocked",
        },
    )
    assert response.status_code == 200
    assert dispatch_calls == []


@pytest.mark.parametrize(
    ("dispatch_result", "expected_notice"),
    [
        (
            (True, "dispatch_accepted"),
            "自動修復Loopへの起動要求を受け付けました（最大2タスク。",
        ),
        (
            (False, "dispatch_token_missing"),
            "自動修復Loopは起動できませんでした（理由コード: dispatch_token_missing）。",
        ),
        (
            (False, "loop_already_running"),
            "既存の分散Loopが稼働中のため、新しいLoopは起動していません。",
        ),
    ],
)
def test_complete_route_reports_autorepair_dispatch_outcome_to_line(
    monkeypatch, dispatch_result, expected_notice
):
    from flask import Flask
    import app as line_app

    app = Flask(__name__)
    app.register_blueprint(obsidian_routes.obsidian_bridge_bp)
    app.config.update(TESTING=True)
    monkeypatch.setenv("OBSIDIAN_BRIDGE_KEY", "dummy-bridge-key")
    monkeypatch.setattr(obsidian_routes, "get_job", lambda _job_id: {
        "id": 17, "job_type": "obsidian", "status": "running", "user_id": "dummy-user"
    })
    monkeypatch.setattr(obsidian_routes, "complete_claimed_job", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        obsidian_routes,
        "request_obsidian_incident_repair",
        lambda *args, **kwargs: dispatch_result,
    )
    pushed = []
    monkeypatch.setattr(
        line_app, "_line_push",
        lambda user_id, message: pushed.append((user_id, message)),
    )

    response = app.test_client().post(
        "/api/obsidian/complete",
        headers={"X-Obsidian-Bridge-Key": "dummy-bridge-key"},
        json={
            "job_id": 17,
            "claim_token": "dummy-claim-token",
            "success": False,
            "reply": "Mac側のObsidian処理を停止しました。",
            "error": "local operation failed (RuntimeError)",
            "diagnostic_category": "local_job_failed",
            "diagnostic_detail": "RuntimeError",
        },
    )

    assert response.status_code == 200
    assert len(pushed) == 1
    assert pushed[0][0] == "dummy-user"
    assert expected_notice in pushed[0][1]
