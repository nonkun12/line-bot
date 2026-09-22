import subprocess

import pytest

from core.local_ai_provider import (
    LocalAIConfigurationError,
    ask_local_ai,
    local_ai_command,
)


def test_local_ai_command_accepts_allowlisted_cli(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_COMMAND", "ollama run qwen2.5-coder:7b")
    assert local_ai_command() == ("ollama", "run", "qwen2.5-coder:7b")


def test_local_ai_command_rejects_non_allowlisted_executable(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_COMMAND", "python helper.py")
    with pytest.raises(LocalAIConfigurationError):
        local_ai_command()


def test_ask_local_ai_does_not_use_shell(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_TIMEOUT_SECONDS", "30")
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="{\"file\": \"tests/test_management_router.py\"}", stderr="")

    monkeypatch.setattr("core.local_ai_provider.subprocess.run", fake_run)
    result = ask_local_ai(("ollama", "run", "qwen2.5-coder:7b"), "system", "user")

    assert result.startswith("{")
    assert calls["command"] == ["ollama", "run", "qwen2.5-coder:7b"]
    assert calls["kwargs"]["shell"] is not True
    assert calls["kwargs"]["timeout"] == 30
    assert "SYSTEM INSTRUCTIONS:" in calls["kwargs"]["input"]


def test_ask_local_ai_rejects_oversized_output(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_TIMEOUT_SECONDS", "30")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="x" * 20_001, stderr="")

    monkeypatch.setattr("core.local_ai_provider.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="exceeded"):
        ask_local_ai(("ollama", "run", "qwen2.5-coder:7b"), "system", "user")
