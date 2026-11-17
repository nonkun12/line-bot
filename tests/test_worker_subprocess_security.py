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
