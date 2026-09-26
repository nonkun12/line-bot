import os

import pytest


def test_hermes_preparation_failure_is_not_recorded_as_invoked(monkeypatch, tmp_path):
    from scripts import run_guarded_runtime as guarded

    monkeypatch.setenv("HERMES_ADVISOR_ENABLED", "true")
    monkeypatch.delenv("HERMES_ADVISOR_INVOKED", raising=False)
    monkeypatch.delenv("HERMES_ADVISOR_USED", raising=False)

    def fail_load(self):
        raise OSError("history unavailable")

    called = {"value": False}

    def fail_if_called(prompt):
        called["value"] = True
        return "should not run"

    monkeypatch.setattr(guarded.SelfImprovementHistory, "load", fail_load)
    monkeypatch.setattr(guarded, "run_hermes_advisor", fail_if_called)

    result = guarded._augment_with_hermes_advice("safe task", tmp_path / "history.jsonl")

    assert result == "safe task"
    assert called["value"] is False
    assert os.environ["HERMES_ADVISOR_INVOKED"] == "false"
    assert os.environ["HERMES_ADVISOR_USED"] == "false"
    assert os.environ["HERMES_ADVISOR_REASON"] == "advisor_preparation_error:OSError"
    assert os.environ["HERMES_ADVISORY_EXCERPT"] == ""


def test_hermes_advice_is_used_without_persisting_model_output(monkeypatch, tmp_path):
    from scripts import run_guarded_runtime as guarded

    monkeypatch.setenv("HERMES_ADVISOR_ENABLED", "true")

    class Analysis:
        recurring_patterns = []

    monkeypatch.setattr(guarded.SelfImprovementHistory, "load", lambda self: object())
    monkeypatch.setattr(guarded, "analyze_signals", lambda *args, **kwargs: Analysis())
    monkeypatch.setattr(guarded, "build_self_improvement_prompt", lambda instruction, evidence: instruction)
    monkeypatch.setattr(guarded, "run_hermes_advisor", lambda prompt: "SECRET-DO-NOT-PERSIST")

    result = guarded._augment_with_hermes_advice("safe task", tmp_path / "history.jsonl")

    assert "UNTRUSTED HERMES ADVISORY:" in result
    assert "SECRET-DO-NOT-PERSIST" in result
    assert os.environ["HERMES_ADVISOR_INVOKED"] == "true"
    assert os.environ["HERMES_ADVISOR_USED"] == "true"
    assert os.environ["HERMES_ADVISORY_EXCERPT"] == ""
