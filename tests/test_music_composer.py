from core.agents import AgentRequest
from agents.music.node import MusicAgent
from agents.music.provider import CompositionRequest, CompositionResult

class FakeProvider:
    name = "fake"
    def compose(self, request: CompositionRequest) -> CompositionResult:
        return CompositionResult("generated", "fake artifact", self.name)

def test_composer_uses_injected_provider():
    response = MusicAgent(FakeProvider()).handle(AgentRequest("u1", "作曲して"))
    assert response.metadata["generation_status"] == "generated"
    assert response.metadata["provider"] == "fake"

def test_default_composer_fails_closed():
    response = MusicAgent().handle(AgentRequest("u1", "作曲して"))
    assert response.metadata["generation_status"] == "not_configured"
    assert "音源生成プロバイダーはまだ未接続" in response.text
