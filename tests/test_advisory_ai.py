from __future__ import annotations

from types import SimpleNamespace

from core.advisory_ai import generate_advisory_text


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="advisory result"))]
        )


class FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_advisory_boundary_never_emits_tool_arguments() -> None:
    client = FakeClient()
    result = generate_advisory_text(
        messages=[{"role": "user", "content": "analyze"}],
        client=client,
    )

    assert result == "advisory result"
    assert client.chat.completions.kwargs is not None
    assert "tools" not in client.chat.completions.kwargs
    assert "tool_choice" not in client.chat.completions.kwargs
