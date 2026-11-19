from __future__ import annotations

import json
import subprocess

import pytest

from scripts import openclaw_mac_bridge as worker


def test_server_url_requires_https_except_loopback():
    assert worker.validate_config("https://example.test/api/openclaw", "x" * 24)
    assert worker.validate_config("http://127.0.0.1:5000/api/openclaw", "x" * 24)
    with pytest.raises(ValueError):
        worker.validate_config("http://example.test/api/openclaw", "x" * 24)


def test_server_url_requires_strong_key():
    with pytest.raises(ValueError):
        worker.validate_config("https://example.test/api/openclaw", "short")


@pytest.mark.parametrize("url", [
    "https://user:pass@example.test/api/openclaw",
    "https://example.test/other",
    "https://example.test/prefix/api/openclaw",
    "https://example.test/api/openclaw?token=secret",
])
def test_server_url_rejects_credentials_query_and_wrong_path(url):
    with pytest.raises(ValueError):
        worker.validate_config(url, "x" * 24)


def test_resolve_workspace_requires_existing_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    assert worker.resolve_workspace() == str(tmp_path.resolve())
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        worker.resolve_workspace()


def test_run_openclaw_uses_exec_and_explicit_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"ok": True, "final": "completed"}), stderr=""
        )

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    assert worker.run_openclaw("inspect repository", 60, job_id=42) == "completed"
    args = captured["args"]
    assert args[:5] == ["/usr/local/bin/openclaw", "agent", "exec", "--cwd", str(tmp_path)]
    assert args[5:8] == ["--timeout", "60", "--json"]
    assert "--message" not in args
    assert "Do not merge, push, deploy" in args[-1]
    assert "inspect repository" in args[-1]
    assert captured["kwargs"]["timeout"] == 90
    assert "shell" not in captured["kwargs"]


def test_process_one_rejects_invalid_claim_envelope(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"ok": False, "job": {"id": 1}}

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse()

    with pytest.raises(RuntimeError, match="invalid claim response"):
        worker.process_one(FakeClient(), "https://example.test/api/openclaw", {}, 60)


def test_process_one_rejects_oversized_queued_message(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse({
                "ok": True,
                "job": {"id": 1, "claim_token": "opaque", "message": "x" * (worker.MAX_MESSAGE_CHARS + 1)},
            })

    with pytest.raises(RuntimeError, match="invalid job payload"):
        worker.process_one(FakeClient(), "https://example.test/api/openclaw", {}, 60)


def test_run_openclaw_rejects_unsuccessful_json(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    monkeypatch.setattr(
        worker.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({"ok": False, "final": "partial"}), stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="unsuccessful"):
        worker.run_openclaw("inspect", 60)


def test_run_openclaw_accepts_final_for_cleanup_only_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    monkeypatch.setattr(
        worker.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps({
                "ok": False,
                "final": "BRIDGE_TEST_OK",
                "error": {"kind": "cleanup", "message": "permission denied"},
            }),
            stderr="",
        ),
    )
    reply = worker.run_openclaw("test", 60)
    assert "BRIDGE_TEST_OK" in reply
    assert "後片付けでエラー" in reply


def test_run_openclaw_rejects_other_unsuccessful_json(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    monkeypatch.setattr(
        worker.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({
                "ok": False, "final": "partial",
                "error": {"kind": "model", "message": "failed"},
            }), stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="unsuccessful"):
        worker.run_openclaw("inspect", 60)


def test_run_openclaw_timeout_is_propagated(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        worker.run_openclaw("inspect repository", 60, job_id=44)


def test_run_openclaw_accepts_cleanup_only_error_with_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    monkeypatch.setattr(
        worker.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, stdout=json.dumps({
                "ok": False,
                "final": "LINE_BRIDGE_OK",
                "error": {"kind": "cleanup", "message": "permission denied"},
            }), stderr="private local path"
        ),
    )
    reply = worker.run_openclaw("test", 60)
    assert "LINE_BRIDGE_OK" in reply
    assert "後片付けでエラー" in reply


def test_run_openclaw_rejects_nonzero_exit_for_non_cleanup_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    monkeypatch.setattr(
        worker.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, stdout=json.dumps({
                "ok": False,
                "final": "partial",
                "error": {"kind": "model", "message": "failed"},
            }), stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="unsuccessful"):
        worker.run_openclaw("test", 60)
