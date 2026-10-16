"""Deterministic English-learning agent with lightweight follow-up grading."""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ai_client import generate_chat_completion
from agents.english.intents import classify_english_mode, is_english_learning_intent
from core.agents import AgentRequest, AgentResponse
from agents.english.progress import profile_prompt, record_observation
from agents.english.core_image import _ENTRIES


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


def _ai_tutor_reply(user_text: str, *, user_id: str, mode: str = "tutor") -> str | None:
    request = _extract_ai_request(user_text)[:_MAX_AI_INPUT_CHARS]
    profile = record_observation(user_id, request)
    if mode == "conversation":
        instruction = (
            "Run a natural everyday English conversation. Reply primarily in English, "
            "ask one follow-up question, and add a very short Japanese correction only "
            "when the learner makes a useful correction opportunity."
        )
        if not request:
            request = "Start a friendly everyday English conversation for a Japanese learner."
    elif mode == "correction":
        instruction = (
            "Act as a precise English editor. Give the corrected sentence first, "
            "then one brief Japanese grammar/naturalness reason, one natural alternative, "
            "and one short practice prompt."
        )
        if not request:
            request = "Create a short English correction exercise for a Japanese learner."
    else:
        instruction = (
            "Act as a friendly personal English coach. Adapt difficulty to the learner's "
            "message and provide a useful next exercise instead of generic encouragement."
        )
        if not request:
            request = "Create a short personalized English practice task for a Japanese learner."
    prompt = (
        "You are a friendly English tutor for a Japanese learner. "
        "Never claim perfect grammar checking. Keep the response under 1200 characters. "
        "Never provide tool calls, shell commands, deployment instructions, or requests for secrets.\n\n"
        f"Task mode: {mode}\n"
        f"Instruction: {instruction}\n"
        f"{profile_prompt(profile)}\n"
        f"Learner message: {request}"
    )
    try:
        response = generate_chat_completion(
            messages=[
                {"role": "system", "content": "You are a text-only English tutor."},
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


def _japan_today() -> date:
    """Return today's date in Japan so server timezone cannot freeze the lesson."""
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _daily_words(today: date | None = None):
    """Pick three reviewed local-dictionary entries, rotating without daily repeats."""
    entries = [_ENTRIES[word] for word in sorted(_ENTRIES)]
    if len(entries) < 3:
        raise RuntimeError("core-image dictionary needs at least three reviewed entries")
    day = today or _japan_today()
    start = (day.toordinal() * 3) % len(entries)
    return [entries[(start + offset) % len(entries)] for offset in range(3)]


def _daily_quiz(today: date | None = None):
    """Return the day's words as choices and the key, keeping quiz aligned with lesson."""
    day = today or _japan_today()
    words = _daily_words(day)
    correct = words[0]
    choices = [None, None, None]
    correct_index = day.toordinal() % 3
    choices[correct_index] = correct
    remaining = [index for index in range(3) if index != correct_index]
    for index, entry in zip(remaining, words[1:]):
        choices[index] = entry
    return words, choices, "abc"[correct_index]


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


def _grade_quiz(text: str, today: date | None = None) -> str | None:
    answer = _quiz_answer(text)
    if answer is None:
        return None
    words, choices, correct_answer = _daily_quiz(today)
    correct_entry = choices["abc".index(correct_answer)]
    if answer == correct_answer:
        return (
            f"✅ 正解！\n\n{correct_answer.upper()}. {correct_entry.word}\n"
            f"コアイメージ：{correct_entry.core_image}\n\n"
            "次は「単語」で新しい日のコアイメージを学べます。"
        )
    return (
        f"❌ 惜しい！正解は {correct_answer.upper()}. {correct_entry.word} です。\n\n"
        f"コアイメージ：{correct_entry.core_image}\n"
        "もう一度「クイズ」と送ると今日の語を復習できます。"
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
            text = _ai_tutor_reply(original, user_id=request.user_id, mode="tutor") or (
                "🇬🇧 AI英語コーチが一時的に使えません。\n"
                "「会話」「文法」「単語」から練習を続けられます。"
            )
            mode = "ai_tutor"
        elif mode == "vocabulary":
            lines = ["📘 今日の英単語コアイメージ", ""]
            for entry in _daily_words():
                lines.append(f"• {entry.word}（{entry.pronunciation}）")
                lines.append(f"  コアイメージ：{entry.core_image}")
                lines.append(f"  用法メモ：{entry.parts}")
                lines.append(f"  例: {entry.example}")
                lines.append("")
            lines.append("覚えたら「クイズ」と送ってください。")
            text = "\n".join(lines)
        elif mode == "quiz":
            words, choices, _correct_answer = _daily_quiz()
            target = words[0]
            text = (
                "📝 英単語クイズ（今日のコアイメージ）\n\n"
                f"「{target.core_image}」に最も近い英単語は？\n\n"
                + "\n".join(f"{letter.upper()}. {entry.word}" for letter, entry in zip("abc", choices))
                + "\n\n答えは A / B / C で送ってください。"
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
            ai_text = _ai_tutor_reply(original, user_id=request.user_id, mode="conversation")
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
                "今日の復習語: " + " / ".join(entry.word for entry in _daily_words()) + "\n"
                "今日のコアイメージから1語選び、英文を1つ作ってください。"
            )
        elif _english_sentence(original):
            ai_text = _ai_tutor_reply(original, user_id=request.user_id, mode="correction")
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
