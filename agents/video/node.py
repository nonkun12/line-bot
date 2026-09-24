"""Video specialist agent for bounded scenario/storyboard planning."""
from __future__ import annotations

from core.agents import AgentRequest, AgentResponse
from agents.video.intents import is_video_intent
from agents.video.pipeline import build_initial_plan


class VideoAgent:
    name = "video"
    description = (
        "Video planning, scenario writing, storyboarding, shot design, and "
        "provider-neutral generation planning."
    )
    priority = 84
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_video_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        plan = build_initial_plan(request.message)
        message = request.message.strip().lower()
        if "編集" in message:
            mode = "editing"
        elif "台本" in message or "シナリオ" in message:
            mode = "script"
        else:
            mode = "production_plan"

        scene_lines = [
            f"{scene.scene_id}: {scene.narration} / {scene.duration_seconds}s"
            for scene in plan.scenes
        ]
        reply = (
            "🎬 Video Agentを起動しました.\n\n"
            "文章を映像制作向けのシーン構成へ変換しました。\n"
            f"タイトル: {plan.title}\n"
            f"シーン数: {len(plan.scenes)}\n"
            f"画角: {plan.aspect_ratio}\n\n"
            + "\n".join(scene_lines)
            + "\n\n"
            "次段階では各シーンの画像生成→動画生成→音声/編集へ接続できます。"
            "外部生成プロバイダ未設定時は安全に計画段階で停止します。"
        )
        return AgentResponse(
            text=reply,
            metadata={
                "feature": self.name,
                "status": "online",
                "mode": "production_plan",
                "scene_count": len(plan.scenes),
                "provider_generation": "fail_closed",
            },
        )


agent = VideoAgent()
