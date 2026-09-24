"""Web/Website specialist agent."""
from __future__ import annotations

from agents.web.intents import is_web_intent
from agents.web.pipeline import build_initial_site_plan, WebProductionPipeline
from core.agents import AgentRequest, AgentResponse


class WebAgent:
    name = "web"
    description = "Website planning, multi-page static site generation, and frontend structure."
    priority = 86
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_web_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        pipeline = WebProductionPipeline()
        plan = build_initial_site_plan(request.message)
        bundle = pipeline.generate(plan)
        pages = ", ".join(f"{page.slug}.html" for page in plan.pages)
        return AgentResponse(
            text=(
                "🌐 Web制作AIを起動しました。\n\n"
                f"サイト: {plan.title}\n"
                f"ページ数: {len(plan.pages)}\n"
                f"生成ファイル: {pages}, styles.css, script.js\n\n"
                "外部API・外部配信先は追加せず、ローカルで確認できる静的サイトとして生成しました。"
            ),
            metadata={
                "feature": self.name,
                "status": "online",
                "mode": "website_generation",
                "page_count": len(plan.pages),
                "generated_file_count": len(bundle.files),
                "external_provider": "none",
            },
        )


agent = WebAgent()
