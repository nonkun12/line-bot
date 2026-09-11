"""Channel-neutral voice intent agent scaffold."""
from __future__ import annotations
from core.agents import AgentRequest, AgentResponse


class VoiceAgent:
    name = "voice"
    description = "Voice input/output and AI speaker requests."
    priority = 85
    enabled = True
    _KEYWORDS = ("音声", "ボイス", "AIスピーカー", "voice", "speaker", "しゃべって")

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.lower()
        return any(keyword.lower() in text for keyword in self._KEYWORDS)

    def handle(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(text="Voice Agentを起動しました。音声入出力は共通Core経由で利用できます。", metadata={"feature": self.name, "status": "scaffold"})

agent = VoiceAgent()
