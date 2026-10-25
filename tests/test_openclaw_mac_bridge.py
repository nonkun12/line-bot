from __future__ import annotations

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


def test_run_openclaw_uses_argument_array(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    captured = {}
    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="completed", stderr="")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    assert worker.run_openclaw("inspect repository", 60) == "completed"
    assert captured["args"] == ["/usr/local/bin/openclaw", "agent", "--message", "inspect repository"]
    assert "shell" not in captured["kwargs"]


def test_run_openclaw_timeout_is_propagated(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/local/bin/openclaw")
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        worker.run_openclaw("inspect repository", 60)
