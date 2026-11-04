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

def test_invalid_animatic_setting_fails_before_claim(monkeypatch):
    monkeypatch.setenv("LOCAL_MEDIA_RENDER_ANIMATIC", "yes")
    monkeypatch.setattr(worker, "_request", lambda *args, **kwargs: pytest.fail("must not claim"))
    with pytest.raises(worker.WorkerError, match="must be 0 or 1"):
        worker.run_once("https://line-bot-yvea.onrender.com", "k" * 32)


def test_animatic_opt_in_is_forwarded_to_local_executor(monkeypatch):
    monkeypatch.setenv("LOCAL_MEDIA_RENDER_ANIMATIC", "1")
    monkeypatch.setattr(worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []
    job = {
        "id": 7, "job_type": "goal_child", "claim_token": "t" * 32,
        "payload": {"executor": "mac_local_media.v1"},
    }

    def fake_request(base_url, internal_key, endpoint, payload=None):
        if endpoint == "/internal/media-jobs/claim":
            return {"ok": True, "claimed": True, "job": job}
        calls.append((endpoint, payload))
        return {"ok": True}

    def fake_execute(received_job, received_payload, **kwargs):
        assert received_job is job
        assert kwargs["render_animatic"] is True
        return {"result": "{}", "evidence": {}}

    monkeypatch.setattr(worker, "_request", fake_request)
    monkeypatch.setattr(worker, "execute_local_media_job", fake_execute)
    assert worker.run_once("https://line-bot-yvea.onrender.com", "k" * 32) is True
    assert calls[0][0] == "/internal/media-jobs/complete"

def test_animatic_dependencies_are_checked_before_claim(monkeypatch):
    monkeypatch.setenv("LOCAL_MEDIA_RENDER_ANIMATIC", "1")
    monkeypatch.setattr(worker.shutil, "which", lambda name: None if name == "blender" else "/usr/bin/ffmpeg")
    monkeypatch.setattr(worker, "_request", lambda *args, **kwargs: pytest.fail("must not claim"))
    with pytest.raises(worker.WorkerError, match="Blender is required"):
        worker.run_once("https://line-bot-yvea.onrender.com", "k" * 32)
