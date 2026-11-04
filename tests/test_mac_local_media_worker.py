from __future__ import annotations

import subprocess

import pytest

from scripts import mac_local_media_worker as worker


def _base_env(monkeypatch):
    monkeypatch.setenv("LINE_BOT_BASE_URL", "https://line-bot-yvea.onrender.com")
    monkeypatch.setenv("LOCAL_MEDIA_OUTPUT_ROOT", "~/Movies/LINE-AI-Media")


def test_configuration_prefers_environment_secret(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "e" * 32)
    monkeypatch.setattr(worker, "_read_keychain_secret", lambda: pytest.fail("Keychain should not be read"))
    assert worker._configuration() == (
        "https://line-bot-yvea.onrender.com",
        "e" * 32,
    )


def test_configuration_reads_fixed_keychain_item_on_macos(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("INTERNAL_PUSH_KEY", raising=False)
    monkeypatch.setattr(worker.sys, "platform", "darwin")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="k" * 32 + "\n", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    assert worker._configuration() == (
        "https://line-bot-yvea.onrender.com",
        "k" * 32,
    )
    assert calls[0][0] == [
        "/usr/bin/security", "find-generic-password",
        "-s", worker.KEYCHAIN_SERVICE, "-a", worker.KEYCHAIN_ACCOUNT, "-w",
    ]
    assert calls[0][1]["timeout"] == 5
    assert calls[0][1]["capture_output"] is True


def test_configuration_fails_closed_when_keychain_item_is_missing(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("INTERNAL_PUSH_KEY", raising=False)
    monkeypatch.setattr(worker.sys, "platform", "darwin")

    def missing_item(*args, **kwargs):
        raise subprocess.CalledProcessError(44, args[0])

    monkeypatch.setattr(worker.subprocess, "run", missing_item)
    with pytest.raises(worker.WorkerError, match="macOS Keychain"):
        worker._configuration()


def test_configuration_rejects_non_https_endpoint_before_claim(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LINE_BOT_BASE_URL", "http://example.com")
    monkeypatch.setenv("INTERNAL_PUSH_KEY", "e" * 32)
    with pytest.raises(worker.WorkerError, match="HTTPS"):
        worker._configuration()
