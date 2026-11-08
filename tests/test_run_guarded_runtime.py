import json

import pytest

from scripts import run_guarded_runtime as guarded_runtime
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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Response(response)


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



class _ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.body = {"error": {"code": code, "message": "provider JSON validation failed"}}


def test_guarded_ask_retries_provider_json_validate_failed():
    client = _Client([
        _ProviderError("json_validate_failed"),
        '{"file":"tests/test_catalog_exhaustion_analyzer.py"}',
    ])

    content = guarded_ask(client, "return JSON", "select a file")

    assert json.loads(content) == {"file": "tests/test_catalog_exhaustion_analyzer.py"}
    assert len(client.completions.calls) == 2
    assert "single valid JSON object only" in client.completions.calls[1]["messages"][0]["content"]


def test_guarded_ask_does_not_retry_other_provider_errors():
    client = _Client([_ProviderError("rate_limit_exceeded"), '{"file":null}'])

    with pytest.raises(_ProviderError):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 1


def test_guarded_ask_fails_closed_after_three_provider_json_validate_failures():
    client = _Client([
        _ProviderError("json_validate_failed"),
        _ProviderError("json_validate_failed"),
        _ProviderError("json_validate_failed"),
    ])

    with pytest.raises(ValueError, match="unusable after bounded JSON retry"):
        guarded_ask(client, "return JSON", "select a file")

    assert len(client.completions.calls) == 3


def test_common_runtime_rea_block_prevents_development_execution(monkeypatch, tmp_path):
    sha = "a" * 40
    rea = {
        "gate": "BLOCKED",
        "reason_code": "rea_high_or_critical_finding",
        "target_sha": sha,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha)
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda root, expected_sha: rea,
    )
    monkeypatch.setattr(
        guarded_runtime.runtime,
        "execute",
        lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")),
    )
    summary_path = tmp_path / "summary.json"
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(summary_path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)

    assert guarded_runtime.main() == 80
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["exit_code"] == 80
    assert summary["rea"] == rea


def test_common_runtime_rea_adapter_exception_blocks_development_execution(monkeypatch, tmp_path):
    sha = "a" * 40
    rea = {
        "gate": "BLOCKED",
        "reason_code": "rea_high_or_critical_finding",
        "target_sha": sha,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    monkeypatch.setattr(guarded_runtime, "_git", lambda *args: sha)
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda root, expected_sha: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        guarded_runtime.runtime,
        "execute",
        lambda instruction: (_ for _ in ()).throw(AssertionError("runtime must not execute")),
    )
    summary_path = tmp_path / "summary.json"
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(summary_path))
    monkeypatch.delenv("GITHUB_ENV", raising=False)

    assert guarded_runtime.main() == 80
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCKED"
    assert summary["exit_code"] == 80
    assert summary["rea"]["reason_code"] == "rea_adapter_error"
    assert summary["rea"]["execution_authorized"] is False


def test_common_runtime_records_rea_evidence_on_success(monkeypatch, tmp_path):
    sha = "b" * 40
    rea = {
        "gate": "PASS",
        "mode": "OBSERVE_ONLY",
        "target_sha": sha,
        "scanner_status": "PASS",
        "finding_count": 0,
        "findings_truncated": False,
        "findings": [],
        "critical_count": 0,
        "blocking_count": 0,
        "execution_authorized": False,
        "patch_authorized": False,
        "hold_clear_authorized": False,
        "merge_deploy_authorized": False,
    }
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: sha if args == ("rev-parse", "HEAD") else "test-branch",
    )
    monkeypatch.setattr(
        "scripts.rea_control_tower_adapter.prepare_rea_evidence",
        lambda root, expected_sha: rea,
    )
    monkeypatch.setattr(guarded_runtime, "_augment_instruction_with_history", lambda instruction, path: instruction)
    monkeypatch.setattr(guarded_runtime, "_augment_with_hermes_advice", lambda instruction, path: instruction)
    monkeypatch.setattr(guarded_runtime.runtime, "execute", lambda instruction: 0)
    monkeypatch.setenv("AUTONOMOUS_SUMMARY_PATH", str(tmp_path / "summary.json"))
    monkeypatch.setenv("DEV_INSTRUCTION", "safe test instruction")
    monkeypatch.delenv("GITHUB_ENV", raising=False)

    assert guarded_runtime.main() == 0
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    assert summary["rea"] == rea


def test_write_summary_preserves_only_allowlisted_failure_code(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_FAILURE_CODE", "existing_test_modified_repair_failed")
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: "a" * 40 if args[0] == "rev-parse" else "main",
    )
    summary = tmp_path / "summary.json"

    guarded_runtime._write_summary("FAIL", 1, "a" * 40, summary)

    assert json.loads(summary.read_text(encoding="utf-8"))["failure_code"] == "existing_test_modified_repair_failed"


def test_write_summary_drops_untrusted_failure_text(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_FAILURE_CODE", "secret=do-not-copy")
    monkeypatch.setattr(
        guarded_runtime,
        "_git",
        lambda *args: "a" * 40 if args[0] == "rev-parse" else "main",
    )
    summary = tmp_path / "summary.json"

    guarded_runtime._write_summary("FAIL", 1, "a" * 40, summary)

    assert "failure_code" not in json.loads(summary.read_text(encoding="utf-8"))
