import json

import core.creator_critic_runtime as runtime
from core.creator_critic_runtime import build_creator_critic_loop, groq_model_call, openai_compatible_model_call


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Response",
            (),
            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "model output"})()})()]},
        )()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


def test_groq_model_call_uses_configured_model_and_returns_text(monkeypatch):
    monkeypatch.setenv("CREATOR_CRITIC_MODEL", "test-model")
    client = FakeClient()

    result = groq_model_call("hello", client=client)

    assert result == "model output"
    request = client.chat.completions.calls[0]
    assert request["model"] == "test-model"
    assert request["messages"] == [{"role": "user", "content": "hello"}]
    assert request["temperature"] == 0.2


def test_creator_critic_loop_can_use_injected_model_without_network():
    calls = []

    def fake_model(prompt):
        calls.append(prompt)
        return "bounded proposal"

    loop = build_creator_critic_loop(model_call=fake_model, max_iterations=1)
    results = loop.run(
        "improve reliability",
        lambda candidate: {"accuracy": 0.9, "stability": 0.9, "efficiency": 0.8, "safety": 1.0},
    )

    assert len(results) == 1
    assert results[0].evaluation.passed is True
    assert len(calls) == 2
    assert "CREATOR" in calls[0]
    assert "CRITIC" in calls[1]



def test_local_openai_compatible_call_uses_configured_endpoint_without_network(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "local output"}}]}).encode()

    class FakeOpener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode())
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(handler):
        assert isinstance(handler, runtime._RejectRedirects)
        return FakeOpener()

    monkeypatch.setattr(runtime, "build_opener", fake_build_opener)
    monkeypatch.setenv("CREATOR_CRITIC_BASE_URL", "http://127.0.0.1:8081/v1/")
    monkeypatch.setenv("CREATOR_CRITIC_MODEL", "local-bonsai-model")
    monkeypatch.setenv("CREATOR_CRITIC_API_KEY", "")

    result = openai_compatible_model_call("hello")

    assert result == "local output"
    assert captured["url"] == "http://127.0.0.1:8081/v1/chat/completions"
    assert captured["body"]["model"] == "local-bonsai-model"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["timeout"] == 15.0


def test_builder_selects_local_endpoint_only_when_explicitly_configured(monkeypatch):
    monkeypatch.setenv("CREATOR_CRITIC_BASE_URL", "http://127.0.0.1:8081/v1")
    monkeypatch.setenv("CREATOR_CRITIC_MODEL", "local-bonsai-model")
    loop = build_creator_critic_loop(max_iterations=1)

    assert loop.creator._model is openai_compatible_model_call


def test_local_model_call_fails_closed_without_endpoint(monkeypatch):
    monkeypatch.delenv("CREATOR_CRITIC_BASE_URL", raising=False)
    monkeypatch.setenv("CREATOR_CRITIC_MODEL", "local-bonsai-model")

    try:
        openai_compatible_model_call("hello")
    except RuntimeError as exc:
        assert str(exc) == "CREATOR_CRITIC_BASE_URL is required for local model execution"
    else:
        raise AssertionError("missing endpoint must fail closed")



def test_local_model_call_rejects_non_loopback_endpoint(monkeypatch):
    monkeypatch.setenv("CREATOR_CRITIC_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("CREATOR_CRITIC_MODEL", "remote-model")

    try:
        openai_compatible_model_call("do not send this externally")
    except RuntimeError as exc:
        assert str(exc) == "local model endpoint must use a loopback URL"
    else:
        raise AssertionError("non-loopback endpoint must be rejected")



def test_local_model_redirects_are_rejected():
    handler = runtime._RejectRedirects()

    assert handler.redirect_request(
        None, None, 302, "Found", {}, "https://attacker.example/collect"
    ) is None
