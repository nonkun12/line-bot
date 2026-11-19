"""Safe first-stage job-seeking AI agent."""
from __future__ import annotations

from agents.jobs.intents import classify_job_mode, extract_job_keywords, is_job_seeking_intent
from core.agents import AgentRequest, AgentResponse


class JobSeekingAgent:
    name = "job_seeking"
    description = "Job search, career documents, application tracking, and interview preparation."
    priority = 85
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_job_seeking_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        mode = classify_job_mode(request.message)
        keywords = extract_job_keywords(request.message)

        prompts = {
            "search": (
                "💼 求職AIを起動しました。\n\n"
                "求人検索モードです。外部求人サイトの接続がまだないため、存在しない求人は生成しません。\n\n"
                "条件: 職種 / 勤務地 / 年収下限 / リモート可否 / 必須スキル"
            ),
            "resume": (
                "📄 履歴書AIモードです。\n\n"
                "希望職種 / 職歴 / 実績 / スキル / 資格 / 希望条件を整理します。"
            ),
            "career_history": (
                "🧾 職務経歴書AIモードです。\n\n"
                "会社名 / 期間 / 役割 / 担当業務 / 成果 / 使用技術を整理します。"
            ),
            "application": (
                "✉️ 応募書類AIモードです。\n\n"
                "求人票と経験・志望理由を基に、根拠のある応募文を作成します。"
            ),
            "interview": (
                "🎤 面接対策AIモードです。\n\n"
                "想定質問 → 回答案 → 深掘り質問 → 改善ポイントで練習します。"
            ),
            "career": (
                "💼 求職AIのキャリア整理モードです。\n\n"
                "希望職種、経験、得意分野、勤務地、年収、働き方を次のアクションへ整理します。"
            ),
        }
        text = prompts[mode]
        if keywords:
            text += "\nキーワード: " + ", ".join(keywords)
        return AgentResponse(
            text=text,
            metadata={"feature": self.name, "status": "online", "mode": mode, "keywords": keywords},
        )


agent = JobSeekingAgent()
