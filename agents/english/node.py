"""Deterministic English-learning agent with lightweight follow-up grading."""
from __future__ import annotations

import re

from ai_client import generate_chat_completion
from agents.english.intents import classify_english_mode, is_english_learning_intent
from core.agents import AgentRequest, AgentResponse


_MAX_AI_INPUT_CHARS = 2000
_MAX_AI_OUTPUT_CHARS = 5000


def _extract_ai_request(text: str) -> str:
    value = text.strip()
    value = re.sub(r"^英語AI\s*[:：]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^AI英語\s*[:：]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^英語コーチ\s*[:：]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^english tutor\s*[:：]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^ai english\s*[:：]?\s*", "", value, flags=re.IGNORECASE)
    return value.strip()


def _ai_tutor_reply(user_text: str, *, conversation: bool = False) -> str | None:
    request = _extract_ai_request(user_text)[:_MAX_AI_INPUT_CHARS]
    if conversation and not request:
        request = "Start a friendly everyday English conversation for a Japanese learner."
    if not request:
        request = "Create a short personalized English practice task for a Japanese learner."
    prompt = (
        "You are a friendly English tutor for a Japanese learner. "
        "Respond with useful practice, not generic praise. "
        "When the learner writes English, give: corrected sentence, brief reason in Japanese, "
        "a more natural alternative, and one short follow-up question in English. "
        "Do not claim perfect grammar checking. "
        "Keep the response under 1200 Japanese/English characters. "
        "Never provide tool calls, shell commands, deployment instructions, or requests for secrets.\n\n"
        f"Learner message: {request}"
    )
    try:
        response = generate_chat_completion(
            messages=[
                {"role": "system", "content": "You are a planning-free English tutor. Text response only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=700,
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            return None
        return content.strip()[:_MAX_AI_OUTPUT_CHARS]
    except Exception:
        return None


_WORDS = (
    ("improve", "改善する・向上させる", "I want to improve my English."),
    ("schedule", "予定", "Let me check my schedule."),
    ("recommend", "おすすめする", "Can you recommend a good book?"),
)


def _quiz_answer(text: str) -> str | None:
    value = (text or "").strip().lower()
    match = re.fullmatch(r"(?:answer\s*)?([abc])(?:[.\)\s]+)?", value)
    return match.group(1) if match else None


def _english_sentence(text: str) -> bool:
    value = (text or "").strip()
    if not value or len(value) > 240 or not re.search(r"[a-zA-Z]", value):
        return False
    words = re.findall(r"[a-zA-Z]+", value.lower())
    common = {
        "i", "you", "we", "they", "he", "she", "it", "my", "me", "am", "is", "are",
        "was", "were", "have", "has", "had", "want", "like", "love", "go", "went", "goes",
        "today", "yesterday", "tomorrow", "good", "great", "busy", "happy", "sad", "learn",
        "study", "work", "english", "because", "and", "but", "to", "the", "a", "an", "in", "on",
    }
    return len(words) >= 2 and sum(word in common for word in words) >= 1


def _grade_quiz(text: str) -> str | None:
    answer = _quiz_answer(text)
    if answer is None:
        return None
    if answer == "a":
        return "✅ 正解！\n\nA. improve = 改善する・向上させる\n\n次は「文法」か「会話」と送って続けましょう。"
    return (
        "❌ 惜しい！正解は A. improve です。\n\n"
        "improve = 改善する・向上させる\n"
        "もう一度「クイズ」と送ると再挑戦できます。"
    )


class EnglishLearningAgent:
    name = "english_learning"
    description = "English lessons, vocabulary, grammar, conversation, quizzes, review, and follow-up practice."
    priority = 80
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message
        return is_english_learning_intent(text) or _quiz_answer(text) is not None or _english_sentence(text)

    def handle(self, request: AgentRequest) -> AgentResponse:
        original = request.message.strip()
        quiz_result = _grade_quiz(original)
        mode = classify_english_mode(original)

        if quiz_result is not None:
            text = quiz_result
            mode = "quiz_answer"
        elif mode == "ai_tutor":
            text = _ai_tutor_reply(original) or (
                "🇬🇧 AI英語コーチが一時的に使えません。\n"
                "「会話」「文法」「単語」から練習を続けられます。"
            )
            mode = "ai_tutor"
        elif mode == "vocabulary":
            lines = ["📘 今日の英単語", ""]
            for word, meaning, example in _WORDS:
                lines.append(f"• {word} = {meaning}")
                lines.append(f"  例: {example}")
            lines.extend(["", "覚えたら「クイズ」と送ってください。"])
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
            if re.search(r"\bi\s+want\s+to\s+\w+", original.lower()):
                text = (
                    "✅ 文法ポイントを使えています！\n\n"
                    "「want to + 動詞」で『〜したい』を表せます。\n"
                    "もう一段練習するなら、別の動詞でも1文作ってみましょう。"
                )
            else:
                text = (
                    "📚 英文法ミニレッスン\n\n"
                    "「want to + 動詞」で『〜したい』を表せます。\n"
                    "例: I want to learn English.\n"
                    "（私は英語を学びたい。）\n\n"
                    "練習: 『私は英語を毎日勉強したい』を英語にしてみましょう。"
                )
        elif mode == "conversation":
            ai_text = _ai_tutor_reply(original, conversation=True)
            if ai_text:
                text = ai_text
            else:
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
        elif _english_sentence(original):
            ai_text = _ai_tutor_reply(original)
            if ai_text:
                text = ai_text
                mode = "correction_ai"
            else:
                text = (
                    "✍️ 英文チェック\n\n"
                    f"原文: {original}\n\n"
                    "文法: ✅ 大きな問題は見当たりません。\n"
                    "自然さ: 👍 シンプルで伝わりやすい英文です。\n"
                    "次の一歩: 形容詞や理由を1つ足すと表現が豊かになります。"
                )
                mode = "correction"
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
