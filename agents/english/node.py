"""Deterministic English-learning agent with lightweight follow-up grading."""
from __future__ import annotations

import re

from agents.english.intents import classify_english_mode, is_english_learning_intent
from core.agents import AgentRequest, AgentResponse


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


def _correct_common_grammar(text: str) -> str | None:
    """Apply a small deterministic rule set without pretending to be a full grammar engine."""
    corrected = text.strip()
    rules = (
        (re.compile(r"\bI\s+has\b", re.IGNORECASE), "I have"),
        (re.compile(r"\bI\s+(?:is|are)\b", re.IGNORECASE), "I am"),
        (re.compile(r"\b(?:you|we|they)\s+has\b", re.IGNORECASE), "you have"),
        (re.compile(r"\b(?:he|she|it)\s+have\b", re.IGNORECASE), "he has"),
        (re.compile(r"\bI\s+want\s+(?!to\b)([a-zA-Z]+)\b", re.IGNORECASE), r"I want to \1"),
        (re.compile(r"\bI\s+am\s+go\b", re.IGNORECASE), "I am going"),
    )
    for pattern, replacement in rules:
        updated = pattern.sub(replacement, corrected)
        if updated != corrected:
            return updated
    return None


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
            text = (
                "💬 英会話練習を始めます。\n\n"
                "Me: Hi! How was your day?\n"
                "あなた: 英語で1文返してください。\n\n"
                "送ってくれた英文を、文法・自然さ・より良い表現の3点で添削します。"
            )
        elif mode == "interview":
            text = (
                "🎤 英語面接トレーニングを始めます。\n\n"
                "面接官: Tell me about yourself.\n"
                "あなた: 英語で30〜60秒程度の回答を書いてください。\n\n"
                "回答を送ると、文法・自然さ・面接で使いやすい表現の観点でフィードバックします。"
            )
        elif mode == "business":
            text = (
                "💼 ビジネス英語トレーニングを始めます。\n\n"
                "場面: 海外の同僚とのミーティング\n"
                "まず「予定を確認したい」と英語で1文伝えてみてください。\n\n"
                "送ってくれた英文を、自然さとビジネス向け表現の観点で添削します。"
            )
        elif mode == "review":
            text = (
                "🔁 英語復習モードです。\n\n"
                "今日の復習語: improve / schedule / recommend\n"
                "まず「improve」を使って英文を1つ作ってください。"
            )
        elif _english_sentence(original):
            corrected = _correct_common_grammar(original)
            if corrected is not None:
                text = (
                    "✍️ 英文チェック\n\n"
                    f"原文: {original}\n"
                    f"修正案: {corrected}\n\n"
                    "ポイント: 基本的な語順・主語に合わせた動詞の形を確認しましょう。\n"
                    "もっと詳しく練習するなら「文法」と送ってください。"
                )
            else:
                text = (
                    "✍️ 英文チェック\n\n"
                    f"原文: {original}\n\n"
                    "自動チェックでは明確な基本ルール違反を検出できませんでした。\n"
                    "文脈に応じた自然さまで詳しく確認するには、モデル連携後の高度添削を利用できます。"
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
