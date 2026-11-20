import json
from pathlib import Path

import pytest

from scripts.distributed_loop_execution_approval import authorize_one_task


def _fixtures(tmp_path: Path):
    task = {"id": "approved-task-001", "instruction": "Add one focused regression test.",
            "allowed_paths": ["tests/test_example.py"]}
    queue = tmp_path / "queue.json"
    event = tmp_path / "event.json"
    catalog = tmp_path / "catalog.json"
    queue.write_text(json.dumps({"version": 1, "max_tasks_per_run": 1, "tasks": [task]}))
    catalog.write_text(json.dumps({"version": 1, "tasks": [{**task, "execution_approved": True}]}))
    event.write_text(json.dumps({
        "sender": {"login": "nonkun12"},
        "repository": {"full_name": "nonkun12/line-bot"},
        "inputs": {
            "execution_approval": "APPROVE_EXECUTION", "mode": "normal",
            "approval_task_id": task["id"],
            "approval_instruction_sha256": __import__("hashlib").sha256(task["instruction"].encode()).hexdigest(),
            "approval_allowed_paths_sha256": __import__("hashlib").sha256(
                json.dumps(task["allowed_paths"], separators=(",", ":")).encode()
            ).hexdigest(),
            "approval_base_sha": "a" * 40,
        },
    }))
    return queue, event, catalog


def _authorize(queue, event, catalog):
    return authorize_one_task(queue, event, catalog, base_sha="a" * 40, ref="refs/heads/main",
                              actor="nonkun12", repository="nonkun12/line-bot")


def test_one_exact_dispatch_approval_is_bound_and_queue_is_reduced(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    result = _authorize(queue, event, catalog)
    assert result["status"] == "PASS"
    assert result["authorized_task_count"] == 1
    assert json.loads(queue.read_text())["tasks"][0]["id"] == "approved-task-001"


@pytest.mark.parametrize("field,value", [
    ("approval_task_id", "different-task-001"),
    ("approval_instruction_sha256", "0" * 64),
    ("approval_allowed_paths_sha256", "0" * 64),
    ("approval_base_sha", "b" * 40),
    ("execution_approval", "DENY"),
])
def test_mismatched_or_denied_dispatch_fails_closed(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    data = json.loads(event.read_text())
    data["inputs"][field] = value
    event.write_text(json.dumps(data))
    before = queue.read_text()
    with pytest.raises(ValueError):
        _authorize(queue, event, catalog)
    assert queue.read_text() == before


def test_approval_selects_exactly_one_task_from_multi_task_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    data = json.loads(queue.read_text())
    data["tasks"].append({**data["tasks"][0], "id": "another-task-002"})
    queue.write_text(json.dumps(data))
    result = _authorize(queue, event, catalog)
    assert result["authorized_task_count"] == 1
    assert [task["id"] for task in json.loads(queue.read_text())["tasks"]] == ["approved-task-001"]


def test_non_dispatch_or_wrong_actor_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    queue, event, catalog = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="event_not_authorized"):
        _authorize(queue, event, catalog)


def test_invalid_ref_or_repository_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="event_not_authorized"):
        authorize_one_task(queue, event, catalog, base_sha="a" * 40, ref="refs/heads/feature",
                           actor="nonkun12", repository="nonkun12/line-bot")


def test_unapproved_catalog_task_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    data = json.loads(catalog.read_text())
    data["tasks"][0]["execution_approved"] = False
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not_registered_or_not_approved"):
        _authorize(queue, event, catalog)



def test_one_shot_marker_is_consumed_only_by_guarded_runtime():
    root = Path(__file__).resolve().parents[1]
    approval_helper = (root / "scripts/distributed_loop_execution_approval.py").read_text(encoding="utf-8")
    guarded_runtime = (root / "scripts/run_guarded_runtime.py").read_text(encoding="utf-8")
    assert "_consume_execution_approval" not in approval_helper
    assert "consumption = _consume_execution_approval(approval_evidence, start_sha)" in guarded_runtime



def test_cli_requires_and_accepts_catalog_argument(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    queue, event, catalog = _fixtures(tmp_path)
    output_file = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update({
        "GITHUB_OUTPUT": str(output_file),
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "nonkun12",
        "GITHUB_REPOSITORY": "nonkun12/line-bot",
    })
    result = subprocess.run(
        [sys.executable, "-m", "scripts.distributed_loop_execution_approval",
         "--queue", str(queue), "--event", str(event),
         "--catalog", str(catalog), "--base-sha", "a" * 40],
        cwd=Path(__file__).resolve().parents[1],
        env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"status": "PASS"' in result.stdout
    assert "consumption" in result.stdout
    assert output_file.read_text(encoding="utf-8") == "task_id=approved-task-001\n"


def test_guarded_runtime_consumes_task_bound_approval_with_atomic_ref(tmp_path, monkeypatch):
    import hashlib
    import io
    import json
    from types import SimpleNamespace
    import scripts.run_guarded_runtime as runtime

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    evidence = {
        "execution_authorized": True,
        "actor": "nonkun12",
        "task_id": "approved-task-001",
        "instruction_sha256": "1" * 64,
        "allowed_paths_sha256": "2" * 64,
    }
    start_sha = "a" * 40
    captured = {}

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            identity = {
                "repository": "nonkun12/line-bot",
                "actor": evidence["actor"],
                "task_id": evidence["task_id"],
                "instruction_sha256": evidence["instruction_sha256"],
                "allowed_paths_sha256": evidence["allowed_paths_sha256"],
                "base_sha": start_sha,
            }
            marker = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            captured["ref"] = f"refs/heads/rsi-approval-consumed/{marker}"
            return json.dumps({
                "ref": captured["ref"],
                "object": {"sha": start_sha},
            }).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(runtime.urllib.request, "urlopen", fake_urlopen)
    result = runtime._consume_execution_approval(evidence, start_sha)
    assert result["gate"] == "PASS"
    assert result["reason_code"] == "approval_consumed_once"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/git/refs")
    assert captured["body"]["ref"] == captured["ref"]
    assert captured["body"]["sha"] == start_sha


def test_guarded_runtime_blocks_reused_approval_marker(tmp_path, monkeypatch):
    import io
    import urllib.error
    import scripts.run_guarded_runtime as runtime

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    evidence = {
        "execution_authorized": True,
        "actor": "nonkun12",
        "task_id": "approved-task-001",
        "instruction_sha256": "1" * 64,
        "allowed_paths_sha256": "2" * 64,
    }

    def already_consumed(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 422, "reference already exists", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr(runtime.urllib.request, "urlopen", already_consumed)
    result = runtime._consume_execution_approval(evidence, "a" * 40)
    assert result == {"gate": "BLOCKED", "reason_code": "approval_already_consumed"}


def test_guarded_runtime_fails_closed_when_approval_ledger_token_is_missing(monkeypatch):
    import scripts.run_guarded_runtime as runtime

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    result = runtime._consume_execution_approval(
        {
            "execution_authorized": True,
            "actor": "nonkun12",
            "task_id": "approved-task-001",
            "instruction_sha256": "1" * 64,
            "allowed_paths_sha256": "2" * 64,
        },
        "a" * 40,
    )
    assert result == {"gate": "BLOCKED", "reason_code": "approval_ledger_token_missing"}



def test_guarded_runtime_blocks_approval_ledger_http_forbidden(monkeypatch):
    import io
    import urllib.error
    import scripts.run_guarded_runtime as runtime

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    evidence = {
        "execution_authorized": True,
        "actor": "nonkun12",
        "task_id": "approved-task-001",
        "instruction_sha256": "1" * 64,
        "allowed_paths_sha256": "2" * 64,
    }

    def forbidden(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 403, "forbidden", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr(runtime.urllib.request, "urlopen", forbidden)
    result = runtime._consume_execution_approval(evidence, "a" * 40)
    assert result == {"gate": "BLOCKED", "reason_code": "approval_ledger_http_403"}


def test_guarded_runtime_blocks_approval_ledger_network_error(monkeypatch):
    import urllib.error
    import scripts.run_guarded_runtime as runtime

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    def unavailable(request, timeout):
        raise urllib.error.URLError("network unavailable")

    monkeypatch.setattr(runtime.urllib.request, "urlopen", unavailable)
    result = runtime._consume_execution_approval(
        {
            "execution_authorized": True,
            "actor": "nonkun12",
            "task_id": "approved-task-001",
            "instruction_sha256": "1" * 64,
            "allowed_paths_sha256": "2" * 64,
        },
        "a" * 40,
    )
    assert result["gate"] == "BLOCKED"
    assert result["reason_code"].startswith("approval_ledger_error:")


def test_guarded_runtime_blocks_invalid_ledger_identity(monkeypatch):
    import scripts.run_guarded_runtime as runtime

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    result = runtime._consume_execution_approval(
        {
            "execution_authorized": True,
            "actor": "nonkun12",
            "task_id": "",
            "instruction_sha256": "1" * 64,
            "allowed_paths_sha256": "2" * 64,
        },
        "a" * 40,
    )
    assert result == {"gate": "BLOCKED", "reason_code": "approval_ledger_identity_invalid"}


def test_guarded_runtime_blocks_malformed_ledger_response(monkeypatch):
    import json
    import scripts.run_guarded_runtime as runtime

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"ref": "refs/heads/wrong", "object": {"sha": "b" * 40}}).encode()

    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda request, timeout: Response())
    result = runtime._consume_execution_approval(
        {
            "execution_authorized": True,
            "actor": "nonkun12",
            "task_id": "approved-task-001",
            "instruction_sha256": "1" * 64,
            "allowed_paths_sha256": "2" * 64,
        },
        "a" * 40,
    )
    assert result == {"gate": "BLOCKED", "reason_code": "approval_ledger_response_invalid"}
