"""Bounded English-learning foundation.

This module is intentionally provider-neutral: future model calls can be
injected without coupling the learning contract to a channel or vendor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.agents import AgentRequest, AgentResponse


@dataclass(frozen=True)
class EnglishLesson:
    prompt: str
    correction: str | None = None
    explanation: str | None = None
    practice: str | None = None


class EnglishLearningAgent:
    name = "english"
    description = "English conversation, correction, and practice."
    priority = 80
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.lower()
        return any(
            marker in text
            for marker in ("英語", "english", "英文", "英会話", "英作文")
        )

    def handle(self, request: AgentRequest) -> AgentResponse:
        lesson = EnglishLesson(prompt=request.message)
        return AgentResponse(
            text=(
                "🇬🇧 英語学習モードです。\n"
                "会話・英文添削・練習問題を共通Coreから処理できます。\n"
                f"入力: {lesson.prompt}"
            ),
            metadata={"feature": self.name, "status": "foundation"},
        )


def build_english_responder(
    responder: Callable[[EnglishLesson], str],
) -> Callable[[AgentRequest], AgentResponse]:
    """Adapt an injected learning model to the channel-neutral Agent contract."""

    def handle(request: AgentRequest) -> AgentResponse:
        lesson = EnglishLesson(prompt=request.message)
        text = str(responder(lesson) or "").strip()
        if not text:
            raise ValueError("English responder returned empty text")
        return AgentResponse(
            text=text,
            metadata={"feature": "english", "status": "online"},
        )

    return handle


agent = EnglishLearningAgent()
