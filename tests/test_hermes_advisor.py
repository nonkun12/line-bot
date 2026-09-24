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

    monkeypatch.setattr(advisor.subprocess, "run", lambda *args, **kwargs: Result())
    result = advisor.run_hermes_advisor("analyze recurring test failures")
    assert result == "advisory result"


def test_hermes_advisor_fails_closed_when_unavailable(monkeypatch):
    monkeypatch.setattr(advisor, "hermes_available", lambda _binary="hermes": False)
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
