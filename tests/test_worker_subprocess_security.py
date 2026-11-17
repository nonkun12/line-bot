"""Security regression tests for generated test subprocess environments."""
from __future__ import annotations

import os
from unittest.mock import patch

from scripts import line_development_worker_v2 as worker


def test_test_process_environment_strips_known_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "github-write-secret")
    monkeypatch.setenv("GH_TOKEN", "gh-write-secret")
    monkeypatch.setenv("GROQ_API_KEY", "provider-secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "line-secret")
    monkeypatch.setenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", "sheets-secret")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "slack-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = worker._test_process_env()

    for name in (
        "GITHUB_TOKEN", "GH_TOKEN", "GROQ_API_KEY",
        "LINE_CHANNEL_ACCESS_TOKEN", "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON",
        "SLACK_WEBHOOK_URL",
    ):
        assert name not in env
    assert env["PATH"] == "/usr/bin"


def test_run_passes_explicit_sanitized_environment(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    clean_env = {"PATH": "/safe"}
    worker.run(["python", "-m", "pytest"], env=clean_env)

    assert captured["env"] == clean_env


def test_test_only_worker_path_does_not_require_model_credentials(monkeypatch, capsys):
    monkeypatch.setenv("DEV_INSTRUCTION", "接続テスト")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(worker, "run_tests", lambda: (True, "pytest PASS"))

    def forbidden_client(*args, **kwargs):
        raise AssertionError("test-only path must not initialize a model client")

    monkeypatch.setattr(worker, "Groq", forbidden_client)

    assert worker.main() == 0
    output = capsys.readouterr().out
    assert "no model provider required" in output
    assert "pytest PASS" in output



def test_normal_worker_blocks_when_local_model_configuration_is_missing(monkeypatch, capsys):
    monkeypatch.setenv("DEV_INSTRUCTION", "通常の開発タスク")
    monkeypatch.delenv("RSI_LOCAL_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("RSI_LOCAL_MODEL_NAME", raising=False)
    monkeypatch.delenv("RSI_LOCAL_MODEL_PROTOCOL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert worker.main() == 1
    output = capsys.readouterr().out
    assert "MODEL_PROVIDER=BLOCKED" in output
    assert "local_model_configuration_missing" in output
    assert "GROQ_API_KEY" not in output
