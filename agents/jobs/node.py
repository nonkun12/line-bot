"""Safe first-stage job-seeking AI agent."""
from __future__ import annotations

from agents.jobs.intents import (
    JobSearchCriteria,
    classify_job_mode,
    extract_job_keywords,
    extract_job_search_criteria,
    is_job_seeking_intent,
)
from agents.jobs.search_contract import JobSearchProvider, JobSearchResult, UnavailableJobSearchProvider
from core.agents import AgentRequest, AgentResponse


class JobSeekingAgent:
    name = "job_seeking"
    description = "Job search, career documents, application tracking, and interview preparation."
    priority = 85
    enabled = True

    def __init__(self, search_provider: JobSearchProvider | None = None) -> None:
        self._search_provider = search_provider or UnavailableJobSearchProvider()

    def can_handle(self, request: AgentRequest) -> bool:
        return is_job_seeking_intent(request.message)

    @staticmethod
    def _criteria_text(criteria: JobSearchCriteria) -> str:
        return "\n".join(
            (
                f"職種: {criteria.occupation or '未指定'}",
                f"勤務地: {criteria.location or '未指定'}",
                f"年収下限: {criteria.salary_min_yen:,}円" if criteria.salary_min_yen is not None else "年収下限: 未指定",
                f"リモート: {criteria.remote or '未指定'}",
                f"必須スキル: {', '.join(criteria.skills) if criteria.skills else '未指定'}",
            )
        )

    def handle(self, request: AgentRequest) -> AgentResponse:
        mode = classify_job_mode(request.message)
        keywords = extract_job_keywords(request.message)

        if mode == "search":
            criteria = extract_job_search_criteria(request.message)
            try:
                result = self._search_provider.search(criteria)
            except Exception:
                result = JobSearchResult(status="error", message="求人ソースの検索に失敗しました")
            if not isinstance(result, JobSearchResult):
                result = JobSearchResult(status="error", message="求人ソースの応答形式が不正です")

            if result.status == "ok" and result.listings:
                lines = [
                    "💼 求職AIを起動しました。\n\n"
                    "実求人ソースから取得した結果です。",
                    self._criteria_text(criteria),
                ]
                for listing in result.listings:
                    line = f"\n・{listing.title} / {listing.company}\n  {listing.location}\n  {listing.url}"
                    if listing.salary:
                        line += f"\n  年収: {listing.salary}"
                    lines.append(line)
                text = "\n".join(lines)
            else:
                text = (
                    "💼 求職AIを起動しました。\n\n"
                    "求人検索モードです。存在しない求人は生成しません。\n\n"
                    f"{self._criteria_text(criteria)}\n\n"
                    f"{result.message or '検索結果を取得できませんでした。'}"
                )
            metadata = {
                "feature": self.name,
                "status": "online",
                "mode": mode,
                "keywords": keywords,
                "criteria": criteria.as_dict(),
                "search_status": result.status,
                "result_count": len(result.listings),
            }
            return AgentResponse(text=text, metadata=metadata)

        prompts = {
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
