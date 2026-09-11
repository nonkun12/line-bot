"""Deterministic English-learning MVP agent."""
from __future__ import annotations

from core.agents import AgentRequest, AgentResponse
from agents.english.intents import classify_english_mode, is_english_learning_intent


_WORDS = (
    ("improve", "改善する・向上させる", "I want to improve my English."),
    ("schedule", "予定", "Let me check my schedule."),
    ("recommend", "おすすめする", "Can you recommend a good book?"),
)


class EnglishLearningAgent:
    name = "english_learning"
    description = "English lessons, vocabulary, grammar, conversation, quizzes, and review."
    priority = 80
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_english_learning_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        mode = classify_english_mode(request.message)
        if mode == "vocabulary":
            lines = ["📘 今日の英単語", ""]
            for word, meaning, example in _WORDS:
                lines.append(f"• {word} = {meaning}")
                lines.append(f"  例: {example}")
            lines.append("")
            lines.append("覚えたら「クイズ」と送ってください。")
            text = "\n".join(lines)
        elif mode == "quiz":
            text = (
                "📝 英単語クイズ\n\n"
                "次の意味に一番近い英単語は？\n"
                "「改善する・向上させる」\n\n"
                "A. improve\nB. schedule\nC. recommend\n\n"
                "答えは A / B / C で送ってください。"
            )
        elif mode == "grammar":
            text = (
                "📚 英文法ミニレッスン\n\n"
                "「want to + 動詞」で『〜したい』を表せます。\n"
                "例: I want to learn English.\n"
                "（私は英語を学びたい。）\n\n"
                "練習: 『私は英語を毎日勉強したい』を英語にしてみましょう。"
            )
        elif mode == "conversation":
            text = (
                "💬 英会話練習を始めます。\n\n"
                "Me: Hi! How was your day?\n"
                "あなた: 英語で1文返してください。\n\n"
                "送ってくれた英文を、自然さ・文法・より良い表現の3点で添削します。"
            )
        elif mode == "review":
            text = (
                "🔁 英語復習モードです。\n\n"
                "今日の復習語: improve / schedule / recommend\n"
                "まず「improve」を使って英文を1つ作ってください。"
            )
        else:
            text = (
                "🇬🇧 英語学習を始めましょう。\n\n"
                "「単語」→ vocabulary\n"
                "「文法」→ grammar\n"
                "「会話」→ conversation\n"
                "「クイズ」→ quiz\n"
                "「復習」→ review\n\n"
                "まずは「単語」と送ると今日の3語から始められます。"
            )

        return AgentResponse(
            text=text,
            metadata={"feature": self.name, "status": "online", "mode": mode},
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
    return {
        "final_reply": response.text,
        "agent_results": {agent.name: response.text},
    }
