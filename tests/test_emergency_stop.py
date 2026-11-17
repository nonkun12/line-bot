import pathlib

import pytest

from core import emergency_stop


def test_get_status_uses_shared_ref(monkeypatch):
    calls = []
    def fake_request(method, repository, token, path, payload=None):
        calls.append((method, repository, path))
        return 200, {"ref": emergency_stop.STOP_REF}
    monkeypatch.setattr(emergency_stop, "_request", fake_request)
    assert emergency_stop.get_status("nonkun12/line-bot", "token") is True
    assert calls == [("GET", "nonkun12/line-bot", "/git/ref/heads/control-tower-emergency-stop")]


def test_get_status_false_only_for_confirmed_missing_ref(monkeypatch):
    calls = []
    def fake_request(method, repository, token, path, payload=None):
        calls.append(path)
        if path == "/git/ref/heads/control-tower-emergency-stop":
            return 404, {}
        return 200, {"full_name": "nonkun12/line-bot"}
    monkeypatch.setattr(emergency_stop, "_request", fake_request)
    assert emergency_stop.get_status("nonkun12/line-bot", "token") is False
    assert calls == ["/git/ref/heads/control-tower-emergency-stop", ""]

    monkeypatch.setattr(emergency_stop, "_request", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network")))
    with pytest.raises(RuntimeError):
        emergency_stop.get_status("nonkun12/line-bot", "token")


def test_get_status_blocks_when_repository_access_is_ambiguous(monkeypatch):
    def fake_request(method, repository, token, path, payload=None):
        return (404, {}) if path.endswith("control-tower-emergency-stop") else (404, {})
    monkeypatch.setattr(emergency_stop, "_request", fake_request)
    with pytest.raises(RuntimeError, match="repository_access_unconfirmed"):
        emergency_stop.get_status("nonkun12/line-bot", "token")


def test_clear_stop_does_not_treat_missing_repository_as_already_running(monkeypatch):
    def fake_request(method, repository, token, path, payload=None):
        return (404, {}) if method == "DELETE" else (404, {})
    monkeypatch.setattr(emergency_stop, "_request", fake_request)
    with pytest.raises(RuntimeError, match="repository_access_unconfirmed"):
        emergency_stop.clear_stop("typo/repository", "token")


def test_activate_stop_creates_dedicated_ref(monkeypatch):
    calls = []
    def fake_request(method, repository, token, path, payload=None):
        calls.append((method, path, payload))
        if path.endswith("/main"):
            return 200, {"object": {"sha": "a" * 40}}
        return 201, {"ref": emergency_stop.STOP_REF}
    monkeypatch.setattr(emergency_stop, "_request", fake_request)
    assert emergency_stop.activate_stop("nonkun12/line-bot", "token") == "STOPPED"
    assert calls[1][2] == {"ref": emergency_stop.STOP_REF, "sha": "a" * 40}


def test_line_stop_requires_allowlisted_user(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U-authorized")
    monkeypatch.setattr(emergency_stop, "activate_stop", lambda *a: "STOPPED")
    assert "許可されていません" in emergency_stop.handle_line_command(
        "緊急STOP", "U-other", "token", "nonkun12/line-bot"
    )
    assert "有効化しました" in emergency_stop.handle_line_command(
        "緊急STOP", "U-authorized", "token", "nonkun12/line-bot"
    )


def test_line_resume_never_claims_execution_resumed(monkeypatch):
    monkeypatch.setenv("DEV_ALLOWED_USER_IDS", "U-authorized")
    monkeypatch.setattr(emergency_stop, "clear_stop", lambda *a: "CLEARED")
    reply = emergency_stop.handle_line_command(
        "緊急STOP解除", "U-authorized", "token", "nonkun12/line-bot"
    )
    assert "自動実行は再開しません" in reply


def test_local_stop_file_blocks(monkeypatch, tmp_path):
    stop_file = tmp_path / ".autonomous-loop.stop"
    monkeypatch.delenv("CONTROL_TOWER_KILL_SWITCH", raising=False)
    monkeypatch.delenv("AUTONOMOUS_STOP_FILE", raising=False)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: self == stop_file)
    assert emergency_stop.local_stop_active(tmp_path) is True


def test_environment_kill_switch_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTROL_TOWER_KILL_SWITCH", "true")
    assert emergency_stop.local_stop_active(tmp_path) is True
