from __future__ import annotations

import io
import json
from urllib.request import Request

import pytest

from core.local_model_adapter import LocalModelUnavailable, OllamaLocalModelCall


class FakeResponse:
    def __init__(self, payload: object):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.raw[:limit]


def test_ollama_adapter_posts_to_loopback_and_extracts_content(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"choices": [{"message": {"content": '{"verdict":"PASS","findings":[]}'}}]})

    monkeypatch.setattr("core.local_model_adapter.urlopen", fake_urlopen)
    call = OllamaLocalModelCall(model="lfm3:1.7b-qad-q4_0")
    result = call("Review this bounded result.")

    assert result == '{"verdict":"PASS","findings":[]}'
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["body"]["model"] == "lfm3:1.7b-qad-q4_0"
    assert seen["body"]["stream"] is False
    assert seen["timeout"] == 20.0


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434/v1",
        "http://example.com/v1",
        "http://192.168.1.20:11434/v1",
        "http://user:pass@127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/v1?forward=1",
    ],
)
def test_ollama_adapter_rejects_non_loopback_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError):
        OllamaLocalModelCall(model="local-model", base_url=url)


def test_ollama_adapter_rejects_empty_and_oversized_prompt() -> None:
    call = OllamaLocalModelCall(model="local-model")
    with pytest.raises(ValueError, match="prompt"):
        call(" ")
    with pytest.raises(ValueError, match="prompt"):
        call("x" * 12001)


def test_ollama_adapter_rejects_invalid_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.local_model_adapter.urlopen",
        lambda *_args, **_kwargs: FakeResponse({"choices": []}),
    )
    with pytest.raises(LocalModelUnavailable):
        OllamaLocalModelCall(model="local-model")("Review this.")
