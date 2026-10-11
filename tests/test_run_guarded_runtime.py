import json
from pathlib import Path

import pytest

import scripts.run_guarded_runtime as guarded_runtime
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


def test_guarded_ask_retries_invalid_json_and_returns_object():
    client = _Client(["not json", '{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 2
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "single valid JSON object only" in client.completions.calls[1]["messages"][0]["content"]


def test_guarded_ask_retries_empty_response():
    client = _Client(["", '{"file":null}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": None}
    assert len(client.completions.calls) == 2


def test_guarded_ask_fails_closed_after_three_bad_responses():
    client = _Client(["not json", "still not json", "also not json"])

    with pytest.raises(ValueError, match="unusable after bounded JSON retry"):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 3


def test_guarded_ask_rejects_non_object_json():
    client = _Client(["[1,2,3]", '{"file":"tests/test_management_router.py"}'])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 2


def test_guarded_ask_recovers_on_third_attempt_and_uses_stricter_prompt():
    client = _Client([
        "not json",
        "still not json",
        '{"file":"tests/test_management_router.py"}',
    ])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_management_router.py"}
    assert len(client.completions.calls) == 3
    assert "smallest valid JSON object" in client.completions.calls[2]["messages"][0]["content"]



def test_runtime_summary_carries_current_run_test_evidence(monkeypatch, tmp_path: Path):
    nonce = "d" * 32
    evidence = {
        "schema_version": 1,
        "runner": "scripts/line_development_worker_v2.py::run_tests",
        "run_nonce": nonce,
        "pytest_command": ["/usr/bin/python3", "-m", "pytest", "-q", "--tb=native"],
        "pytest_exit_code": 0,
        "pytest_output_sha256": "e" * 64,
        "py_compile": [],
    }
    monkeypatch.setenv("AUTONOMOUS_RUN_NONCE", nonce)
    monkeypatch.setenv("AUTONOMOUS_TEST_EVIDENCE", json.dumps(evidence))
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: "f" * 40 if args == ("rev-parse", "HEAD") else "test-branch")
    path = tmp_path / "summary.json"

    guarded_runtime._write_summary("PASS", 0, "a" * 40, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["test_evidence"] == evidence


def test_runtime_summary_omits_stale_nonce_test_evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTONOMOUS_RUN_NONCE", "d" * 32)
    monkeypatch.setenv("AUTONOMOUS_TEST_EVIDENCE", json.dumps({
        "schema_version": 1, "runner": "scripts/line_development_worker_v2.py::run_tests",
        "run_nonce": "0" * 32, "pytest_command": ["/usr/bin/python3", "-m", "pytest", "-q", "--tb=native"],
        "pytest_exit_code": 0, "pytest_output_sha256": "e" * 64, "py_compile": [],
    }))
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: "f" * 40 if args == ("rev-parse", "HEAD") else "test-branch")
    path = tmp_path / "summary.json"

    guarded_runtime._write_summary("PASS", 0, "a" * 40, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["test_evidence"] is None
