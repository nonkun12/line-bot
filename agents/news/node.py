"""AI news agent scaffold; source retrieval is added separately."""
from __future__ import annotations
from core.agents import AgentRequest, AgentResponse


class AINewsAgent:
    name = "ai_news"
    description = "AI news retrieval, summarization, and delivery requests."
    priority = 80
    enabled = True
    _KEYWORDS = ("AI NEWS", "AIニュース", "AI ニュース", "人工知能ニュース", "ai news")

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.lower()
        return any(keyword.lower() in text for keyword in self._KEYWORDS)

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="AI NEWS Agentを起動しました。現在はニュース取得・要約基盤の準備段階です。", metadata={"feature": self.name, "status": "scaffold"})

agent = AINewsAgent()
