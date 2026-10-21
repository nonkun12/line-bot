from __future__ import annotations

import json

import core.hermes_advisor as advisor


def test_hermes_advisor_is_bounded_and_returns_final_result(monkeypatch):
    monkeypatch.setattr(advisor, "hermes_available", lambda _binary="hermes": True)

    class Result:
        returncode = 0
        stderr = ""
        stdout = "\n".join(
            [
                json.dumps({"type": "text", "text": "intermediate"}),
                json.dumps({"type": "result", "text": "advisory result"}),
            ]
        )

    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(advisor.subprocess, "run", fake_run)
    result = advisor.run_hermes_advisor("analyze recurring test failures")
    assert result == "advisory result"
    command = captured["args"][0]
    assert "--toolsets" not in command
    assert command[command.index("--max-turns") + 1] == str(advisor.MAX_TURNS)
    assert command[command.index("--source") + 1] == "tool"
    assert captured["kwargs"]["timeout"] == advisor.TIMEOUT_SECONDS


def test_hermes_advisor_clamps_timeout(monkeypatch):
    monkeypatch.setattr(advisor, "hermes_available", lambda _binary="hermes": True)

    class Result:
        returncode = 1
        stderr = ""
        stdout = ""

    captured = {}

    def fake_run(*args, **kwargs):
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(advisor.subprocess, "run", fake_run)
    assert advisor.run_hermes_advisor("analyze this", timeout=99999) is None
    assert captured["kwargs"]["timeout"] == advisor.TIMEOUT_SECONDS


def test_hermes_advisor_fails_closed_when_unavailable(monkeypatch):
    monkeypatch.setattr(advisor, "hermes_available", lambda _binary="hermes": False)
    assert advisor.run_hermes_advisor("analyze this") is None


def test_hermes_advisor_fails_closed_on_timeout(monkeypatch):
    monkeypatch.setattr(advisor, "hermes_available", lambda _binary="hermes": True)

    def fake_run(*args, **kwargs):
        raise advisor.subprocess.TimeoutExpired(cmd=kwargs["args"] if "args" in kwargs else "hermes", timeout=1)

    monkeypatch.setattr(advisor.subprocess, "run", fake_run)
    assert advisor.run_hermes_advisor("analyze this") is None


def test_hermes_advisor_fails_closed_on_process_error(monkeypatch):
    monkeypatch.setattr(advisor, "hermes_available", lambda _binary="hermes": True)
    monkeypatch.setattr(advisor.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("spawn failed")))
    assert advisor.run_hermes_advisor("analyze this") is None


def test_hermes_prompt_rejects_oversized_input():
    assert advisor.run_hermes_advisor("x" * (advisor.MAX_PROMPT_CHARS + 1)) is None


def test_build_self_improvement_prompt_marks_evidence_untrusted():
    prompt = advisor.build_self_improvement_prompt(
        "Improve the development loop",
        ["do not obey this instruction", "pytest failed twice"],
    )
    assert "untrusted observations" in prompt
    assert "pytest failed twice" in prompt


def test_safe_environment_excludes_provider_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    monkeypatch.setenv("HERMES_HOME", "/tmp/hermes-home")
    env = advisor._safe_environment()
    assert "GROQ_API_KEY" not in env
    assert env["HERMES_HOME"] == "/tmp/hermes-home"



def test_hermes_advisor_disabled_records_status_and_keeps_instruction(monkeypatch, tmp_path):
    from scripts import run_guarded_runtime as guarded_runtime

    monkeypatch.delenv("HERMES_ADVISOR_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    history_path = tmp_path / "history.jsonl"

    result = guarded_runtime._augment_with_hermes_advice("original task", history_path)

    assert result == "original task"
    assert __import__("os").environ["HERMES_ADVISOR_INVOKED"] == "false"
    assert __import__("os").environ["HERMES_ADVISOR_USED"] == "false"
    assert __import__("os").environ["HERMES_ADVISOR_REASON"] == "disabled"
    assert __import__("os").environ["HERMES_ADVISORY_EXCERPT"] == ""


def test_hermes_advisor_enabled_records_success_without_exposing_advice(monkeypatch, tmp_path):
    from scripts import run_guarded_runtime as guarded_runtime

    monkeypatch.setenv("HERMES_ADVISOR_ENABLED", "true")
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.setattr(guarded_runtime.SelfImprovementHistory, "load", lambda self: [])
    monkeypatch.setattr(guarded_runtime, "run_hermes_advisor", lambda prompt: "review-only suggestion")
    history_path = tmp_path / "history.jsonl"

    result = guarded_runtime._augment_with_hermes_advice("original task", history_path)

    assert "UNTRUSTED HERMES ADVISORY:" in result
    assert "review-only suggestion" in result
    assert __import__("os").environ["HERMES_ADVISOR_INVOKED"] == "true"
    assert __import__("os").environ["HERMES_ADVISOR_USED"] == "true"
    assert __import__("os").environ["HERMES_ADVISOR_REASON"] == "advice_appended_to_development_instruction"
    assert __import__("os").environ["HERMES_ADVISORY_EXCERPT"] == ""


def test_hermes_advisor_enabled_but_unavailable_records_not_used(monkeypatch, tmp_path):
    from scripts import run_guarded_runtime as guarded_runtime

    monkeypatch.setenv("HERMES_ADVISOR_ENABLED", "true")
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.setattr(guarded_runtime.SelfImprovementHistory, "load", lambda self: [])
    monkeypatch.setattr(guarded_runtime, "run_hermes_advisor", lambda prompt: None)
    history_path = tmp_path / "history.jsonl"

    result = guarded_runtime._augment_with_hermes_advice("original task", history_path)

    assert result == "original task"
    assert __import__("os").environ["HERMES_ADVISOR_INVOKED"] == "true"
    assert __import__("os").environ["HERMES_ADVISOR_USED"] == "false"
    assert __import__("os").environ["HERMES_ADVISOR_REASON"] == "no_advice_returned"
