"""Security and behavior tests for the local-only model adapter."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from core.local_model_client import LocalModelClient, LocalModelError


@pytest.mark.parametrize("url", [
    "https://api.example.com",
    "http://192.0.2.1:11434",
    "http://127.0.0.1:11434?token=secret",
    "http://user:pass@127.0.0.1:11434",
    "http://127.0.0.1/../remote",
])
def test_remote_or_ambiguous_endpoint_is_rejected(url):
    with pytest.raises(LocalModelError):
        LocalModelClient(url, "local-model", "ollama")


def test_only_explicit_supported_protocols_are_allowed():
    with pytest.raises(LocalModelError):
        LocalModelClient("http://127.0.0.1:11434", "local-model", "cloud")


def test_ollama_payload_and_response_are_adapted(monkeypatch):
    client = LocalModelClient("http://127.0.0.1:11434", "lfm3:local", "ollama")
    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self, _limit):
            return json.dumps({"message": {"content": "local answer"}}).encode()

    class Opener:
        def open(self, req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data)
            captured["timeout"] = timeout
            return Response()

    client.opener = Opener()
    response = client.chat.completions.create(
        model="lfm3:local",
        messages=[{"role": "user", "content": "hello"}],
        max_completion_tokens=123,
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["payload"]["options"]["num_predict"] == 123
    assert response.choices[0].message.content == "local answer"


def test_openai_compatible_loopback_payload_is_adapted():
    client = LocalModelClient("http://[::1]:8083/v1", "bonsai-local", "openai-compatible")
    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self, _limit):
            return b'{"choices":[{"message":{"content":"bonsai answer"}}]}'

    class Opener:
        def open(self, req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data)
            return Response()

    client.opener = Opener()
    response = client.chat.completions.create(
        model="bonsai-local",
        messages=[{"role": "user", "content": "hello"}],
        max_completion_tokens=64,
        reasoning_effort="low",
        include_reasoning=False,
    )

    assert captured["url"] == "http://[::1]:8083/v1/chat/completions"
    assert captured["payload"]["max_tokens"] == 64
    assert response.choices[0].message.content == "bonsai answer"


def test_model_mismatch_is_rejected_before_request():
    client = LocalModelClient("http://localhost:11434", "model-a", "ollama")

    with pytest.raises(LocalModelError, match="model_name_mismatch"):
        client.chat.completions.create(
            model="model-b",
            messages=[{"role": "user", "content": "hello"}],
        )


def test_redirects_are_disabled():
    client = LocalModelClient("http://127.0.0.1:11434", "model-a", "ollama")
    handler = next(h for h in client.opener.handlers if h.__class__.__name__ == "NoRedirect")

    with pytest.raises(LocalModelError, match="redirect_blocked"):
        handler.redirect_request(None, None, 302, "Found", {}, "https://example.com")
