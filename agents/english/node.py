"""English-learning agent scaffold with no external API dependency."""
from __future__ import annotations

from core.agents import AgentRequest, AgentResponse


class EnglishLearningAgent:
    name = "english_learning"
    description = "English learning, practice, vocabulary, and review requests."
    priority = 80
    enabled = True

    _KEYWORDS = ("英語", "英会話", "英単語", "英文", "english", "vocabulary", "speaking", "grammar")

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.lower()
        return any(keyword in text for keyword in self._KEYWORDS)

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            text=(
                "英語学習Agentを起動しました。\n"
                "現在は学習基盤の準備段階です。\n"
                "次に単語・会話練習・復習記録を共通Coreへ接続します。"
            ),
            metadata={"feature": self.name, "status": "scaffold"},
        )


agent = EnglishLearningAgent()


def english_learning_agent_node(state: dict) -> dict:
    request = AgentRequest(
        user_id=str(state.get("user_id", "")),
        message=str(state.get("raw_message", "")),
        channel=str(state.get("channel", "unknown")),
        metadata=state.get("metadata", {}),
    )
    response = agent.handle(request)
    return {"final_reply": response.text, "agent_results": {agent.name: response.text}}
