from core.creator_critic_runtime import build_creator_critic_loop, groq_model_call


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
