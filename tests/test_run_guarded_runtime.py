import json

import pytest

from core import local_ai_provider
from scripts.run_guarded_runtime import guarded_ask


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.responses.pop(0))


class _Client:
    def __init__(self, responses):
        self.completions = _Completions(responses)
        self.chat = type("Chat", (), {"completions": self.completions})()


def test_guarded_ask_retries_invalid_json_and_returns_object(monkeypatch):
    monkeypatch.delenv("LOCAL_AI_COMMAND", raising=False)
    client = _Client(["not json", '{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 2
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "single valid JSON object only" in client.completions.calls[1]["messages"][0]["content"]


def test_guarded_ask_retries_empty_response(monkeypatch):
    monkeypatch.delenv("LOCAL_AI_COMMAND", raising=False)
    client = _Client(["", '{"file":null}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": None}
    assert len(client.completions.calls) == 2


def test_guarded_ask_fails_closed_after_two_bad_responses(monkeypatch):
    monkeypatch.delenv("LOCAL_AI_COMMAND", raising=False)
    client = _Client(["not json", "still not json"])

    with pytest.raises(ValueError, match="unusable after bounded JSON retry"):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 2


def test_guarded_ask_normalizes_raw_control_chars_inside_json_strings(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_COMMAND", "ollama run qwen2.5-coder:7b")
    raw = '{"file":"tests/test_management_router.py","old":"line1
line2","new":"line1
line3"}'

    def local_response(command, system, user):
        return raw

    monkeypatch.setattr(local_ai_provider, "ask_local_ai", local_response)

    content = guarded_ask(None, "return JSON", "build a change")

    parsed = json.loads(content)
    assert parsed["old"] == "line1\nline2"
    assert parsed["new"] == "line1\nline3"


def test_guarded_ask_falls_back_to_external_ai_after_local_failure(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_COMMAND", "ollama run qwen2.5-coder:7b")
    calls = []

    def fail_local(command, system, user):
        calls.append((command, system, user))
        raise RuntimeError("local model unavailable")

    monkeypatch.setattr(local_ai_provider, "ask_local_ai", fail_local)
    client = _Client(['{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(calls) == 1
    assert calls[0][0] == ("ollama", "run", "qwen2.5-coder:7b")
    assert len(client.completions.calls) == 1


def test_guarded_ask_falls_back_after_invalid_local_json(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_COMMAND", "ollama run qwen2.5-coder:7b")
    local_calls = []

    def bad_local(command, system, user):
        local_calls.append(command)
        return "not json"

    monkeypatch.setattr(local_ai_provider, "ask_local_ai", bad_local)
    client = _Client(['{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(local_calls) == 1
    assert len(client.completions.calls) == 1
