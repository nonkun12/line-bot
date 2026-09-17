"""Safe first-stage job-seeking AI agent.

This foundation does not fabricate job listings. External job sources can later
implement the provider-neutral contracts in core.job_search.
"""
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

        if mode == "search":
            text = (
                "💼 求職AIを起動しました。\n\n"
                "求人検索の基準を整理します。まだ外部求人サイトへ直接接続していないため、"
                "存在しない求人を生成することはしません。\n\n"
                "次の形式で条件を送ってください。\n"
                "職種 / 勤務地 / 年収下限 / リモート可否 / 必須スキル\n"
                "例: Python / 東京 / 600万円 / リモート可 / Python, AWS"
            )
        elif mode == "resume":
            text = (
                "📄 履歴書AIモードです。\n\n"
                "以下を送ると、応募先ごとに使い分けられる材料へ整理します。\n"
                "・希望職種\n・職歴\n・実績（数字があれば歓迎）\n・スキル\n・資格\n・希望条件"
            )
        elif mode == "career_history":
            text = (
                "🧾 職務経歴書AIモードです。\n\n"
                "会社名 / 期間 / 役割 / 担当業務 / 成果 / 使用技術 の順に送ってください。\n"
                "事実と成果を分離して、応募先に合わせて再構成できる形にします。"
            )
        elif mode == "application":
            text = (
                "✉️ 応募書類AIモードです。\n\n"
                "求人票の本文と、あなたの経験・志望理由を送ってください。\n"
                "求人票にない情報を捏造せず、根拠がある内容だけで志望動機・応募文を組み立てます。"
            )
        elif mode == "interview":
            text = (
                "🎤 面接対策AIモードです。\n\n"
                "応募先・職種・面接形式を送ってください。\n"
                "想定質問 → 回答案 → 深掘り質問 → 改善ポイントの順で練習できる形にします。"
            )
        else:
            extra = f"\n今回のキーワード候補: {', '.join(keywords)}" if keywords else ""
            text = (
                "💼 求職AIのキャリア整理モードです。\n\n"
                "希望職種、経験、得意分野、勤務地、年収、働き方を送ると、"
                "検索・応募・面接の次のアクションへ分解します。"
                + extra
            )

        return AgentResponse(
            text=text,
            metadata={"feature": self.name, "status": "online", "mode": mode, "keywords": keywords},
        )


agent = JobSeekingAgent()
