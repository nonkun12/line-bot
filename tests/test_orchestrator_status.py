from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import app as app_module
from core.orchestrator_status import (
    build_orchestrator_status_reply,
    is_orchestrator_status_command,
)


def _payload(document):
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    return {
        "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
    }


def _fixtures():
    task = {
        "id": "task-a",
        "instruction": "Read-only test",
        "allowed_paths": ["tests/test_example.py"],
    }
    return {
        ".github/autonomous-loop-tasks.json": {"tasks": [task]},
        ".github/autonomous-loop-task-catalog.json": {"tasks": [task]},
        ".autonomous-loop-state.json": {
            "version": 1,
            "completed": [],
            "recovery_ai": {"schema_version": 1, "tasks": {}},
        },
    }


def test_status_command_aliases_are_read_only():
    assert is_orchestrator_status_command("統括AI 状況確認")
    assert is_orchestrator_status_command("統括AIの状況")
    assert is_orchestrator_status_command("Orchestrator status")
    assert is_orchestrator_status_command("分散Loop 状況確認")
    assert not is_orchestrator_status_command("分散Loop開始")
    assert not is_orchestrator_status_command("Orchestratorを実行")


def test_builder_reads_only_three_sources_and_fails_closed_without_trusted_gates():
    fixtures = _fixtures()
    calls = []

    def getter(url, *, token=""):
        calls.append(url)
        for path, document in fixtures.items():
            if path in url:
                return _payload(document)
        raise AssertionError(f"unexpected read: {url}")

    reply = build_orchestrator_status_reply(
        "nonkun12/line-bot",
        "read-only-test-token",
        get_json=getter,
        now=datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc),
    )
    assert len(calls) == 3
    assert any("ref=main" in url for url in calls)
    assert any("ref=autonomous-loop-state" in url for url in calls)
    assert "判定: BLOCKED" in reply
    assert "サブ4系統: CLOSED" in reply
    assert "実行候補: 0件" in reply
    assert "Global HOLD: 未検証" in reply
    assert "予算: 未検証" in reply
    assert "実行許可: false" in reply
    assert "Actions dispatch: false" in reply


def test_builder_requires_token_and_does_not_call_getter():
    called = []

    def getter(*args, **kwargs):
        called.append(args)
        raise AssertionError("must not call without token")

    reply = build_orchestrator_status_reply(
        "nonkun12/line-bot", "", get_json=getter
    )
    assert "GitHub認証未設定" in reply
    assert "判定: BLOCKED" in reply
    assert called == []


def test_builder_fails_closed_on_malformed_contents():
    reply = build_orchestrator_status_reply(
        "nonkun12/line-bot",
        "read-only-test-token",
        get_json=lambda *args, **kwargs: {"encoding": "none", "content": ""},
    )
    assert "証拠を検証できません" in reply
    assert "判定: BLOCKED" in reply
    assert "実行許可: false" in reply


def test_line_status_routes_to_orchestrator_before_legacy_dispatchers(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "test-user")
    monkeypatch.setattr(app_module, "is_orchestrator_status_command", lambda _message: True)
    monkeypatch.setattr(
        app_module,
        "build_orchestrator_status_reply",
        lambda repository, token: "ORCHESTRATOR_STATUS",
    )
    monkeypatch.setattr(
        app_module,
        "request_distributed_loop",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy route called")),
    )
    monkeypatch.setattr(
        app_module,
        "request_recovery_resume_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy recovery route called")),
    )
    request = type("Request", (), {
        "message": "統括AI 状況確認",
        "user_id": "test-user",
        "channel": "line",
        "metadata": {},
    })()
    assert app_module._handle_ai_gateway_request(request) == "ORCHESTRATOR_STATUS"



def test_line_status_denies_non_allowlisted_user(monkeypatch):
    monkeypatch.setenv("DISTRIBUTED_LOOP_LINE_USER_IDS", "allowed-user")
    monkeypatch.setattr(app_module, "is_orchestrator_status_command", lambda _message: True)
    monkeypatch.setattr(
        app_module,
        "build_orchestrator_status_reply",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("status source must not be queried")),
    )
    request = type("Request", (), {
        "message": "統括AI 状況確認",
        "user_id": "unknown-user",
        "channel": "line",
        "metadata": {},
    })()
    reply = app_module._handle_ai_gateway_request(request)
    assert "許可されていません" in reply

def test_legacy_app_development_dispatch_is_closed(monkeypatch):
    monkeypatch.setattr(app_module, "is_orchestrator_status_command", lambda _message: False)
    monkeypatch.setattr(app_module, "request_distributed_loop", lambda *args, **kwargs: (False, ""))
    monkeypatch.setattr(app_module, "request_recovery_resume_review", lambda *args, **kwargs: (False, ""))
    monkeypatch.setattr(app_module, "is_control_tower_status_command", lambda _message: False)
    monkeypatch.setattr(app_module, "handle_core_image_command", lambda _message: None)
    monkeypatch.setattr(app_module, "extract_app_development_request", lambda _message: "build new app")
    monkeypatch.setattr(
        app_module, "dispatch_app_development_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy app dispatcher called")),
    )
    request = type("Request", (), {
        "message": "アプリ開発: 新規アプリ",
        "user_id": "test-user",
        "channel": "line",
        "metadata": {},
    })()
    reply = app_module._handle_ai_gateway_request(request)
    assert "旧アプリ開発workflowの直接起動は停止中" in reply


def test_legacy_development_dispatch_is_closed(monkeypatch):
    monkeypatch.setattr(app_module, "is_orchestrator_status_command", lambda _message: False)
    monkeypatch.setattr(app_module, "request_distributed_loop", lambda *args, **kwargs: (False, ""))
    monkeypatch.setattr(app_module, "request_recovery_resume_review", lambda *args, **kwargs: (False, ""))
    monkeypatch.setattr(app_module, "is_control_tower_status_command", lambda _message: False)
    monkeypatch.setattr(app_module, "handle_core_image_command", lambda _message: None)
    monkeypatch.setattr(app_module, "extract_app_development_request", lambda _message: None)
    monkeypatch.setattr(app_module, "extract_development_instruction", lambda _message: "fix the code")
    monkeypatch.setattr(
        app_module, "dispatch_development_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy dev dispatcher called")),
    )
    request = type("Request", (), {
        "message": "開発: コードを修正",
        "user_id": "test-user",
        "channel": "line",
        "metadata": {},
    })()
    reply = app_module._handle_ai_gateway_request(request)
    assert "旧開発workflowのLINE直接起動は停止中" in reply
