"""Tests for the one-command local model smoke check."""
from __future__ import annotations

from types import SimpleNamespace

from scripts import local_model_smoke_test


def test_smoke_test_reports_pass_without_exposing_response(monkeypatch, capsys):
    class FakeClient:
        model = "test-local"
        protocol = "ollama"

        class _Completions:
            def create(self, **kwargs):
                assert kwargs["temperature"] == 0.0
                assert kwargs["max_completion_tokens"] == 16
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="LOCAL_MODEL_OK"))]
                )

        chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr(local_model_smoke_test, "create_local_model_client_from_env", lambda: FakeClient())

    assert local_model_smoke_test.main() == 0
    output = capsys.readouterr().out
    assert "LOCAL_MODEL=PASS protocol=ollama model=test-local" in output
    assert "LOCAL_MODEL_OK" not in output


def test_smoke_test_blocks_when_local_configuration_is_missing(monkeypatch, capsys):
    from core.local_model_client import LocalModelError

    def blocked():
        raise LocalModelError("local_model_configuration_missing")

    monkeypatch.setattr(local_model_smoke_test, "create_local_model_client_from_env", blocked)

    assert local_model_smoke_test.main() == 2
    assert "LOCAL_MODEL=BLOCKED" in capsys.readouterr().out
