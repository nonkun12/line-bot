"""Channel-neutral voice agent MVP."""
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
        channel = request.channel or "unknown"
        if request.message.strip():
            text = (
                "🎙️ Voice Agentです。\n"
                "音声入力は共通Coreで受け付け、通常のAI応答経路へ渡せます。\n"
                f"現在の入力チャネル: {channel}"
            )
        else:
            text = "🎙️ Voice Agentです。音声入力を受け付けます。"
        return AgentResponse(
            text=text,
            metadata={"feature": self.name, "status": "online", "channel": channel},
        )


agent = VoiceAgent()


def voice_agent_node(state: dict) -> dict:
    request = AgentRequest(
        user_id=str(state.get("user_id", "")),
        message=str(state.get("raw_message", "")),
        channel=str(state.get("channel", "unknown")),
        metadata=state.get("metadata", {}),
    )
    response = agent.handle(request)
    return {"final_reply": response.text, "agent_results": {agent.name: response.text}}
