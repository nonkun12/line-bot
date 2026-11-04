"""Explicit orchestration boundary between Video AI and Music AI.

This pipeline is provider-neutral and deterministic: Video AI owns the scenario,
Music AI receives that exact validated scenario, and the result is returned as
one audiovisual production package. It does not render or publish media.
"""
from __future__ import annotations

from typing import Any

from agents.music.node import MusicAgent
from agents.video.node import VideoAgent
from agents.video.scenario import scenario_goal_jobs, validate_scenario
from core.agents import AgentRequest, AgentResponse


class VideoMusicPipeline:
    """Run scenario design, music planning, and cross-agent contract checks."""

    name = "video_music_pipeline"

    def __init__(
        self,
        video_agent: VideoAgent | None = None,
        music_agent: MusicAgent | None = None,
    ) -> None:
        self.video_agent = video_agent or VideoAgent()
        self.music_agent = music_agent or MusicAgent()

    def run(self, request: AgentRequest) -> AgentResponse:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        if not self.video_agent.can_handle(request):
            raise ValueError("request is not a video-production request")

        video_response = self.video_agent.handle(request)
        if video_response.metadata.get("mode") != "scenario":
            raise ValueError("video request must explicitly ask for a scenario")
        scenario = video_response.metadata.get("scenario")
        errors = validate_scenario(scenario)
        if errors:
            raise ValueError("Video AI returned an invalid scenario: " + ", ".join(errors))

        metadata = dict(request.metadata)
        metadata["scenario"] = scenario
        metadata["music_genre"] = metadata.get(
            "music_genre", metadata.get("genre", "映像に合わせたオリジナル音楽")
        )
        metadata["instrumentation"] = metadata.get(
            "instrumentation", "映像の世界観に合う編成"
        )
        music_request = AgentRequest(
            user_id=request.user_id,
            message="映像用BGMの作曲設計を作成する",
            channel=request.channel,
            metadata=metadata,
        )
        # Deliberately invoke the specialist selected by this explicit pipeline;
        # no generic intent router is allowed to silently drop the handoff.
        music_response = self.music_agent.handle(music_request)
        plan = music_response.metadata.get("music_plan")
        if music_response.metadata.get("mode") != "audiovisual_score_plan" or not isinstance(plan, dict):
            raise ValueError("Music AI did not return an audiovisual score plan")
        if plan.get("source_scenario_title") != scenario.get("title"):
            raise ValueError("Music AI plan does not reference the source scenario")
        if plan.get("duration_seconds") != scenario["creative_brief"]["duration_seconds"]:
            raise ValueError("Music AI plan duration differs from the source scenario")
        if len(plan.get("cues", [])) != len(scenario["scenes"]):
            raise ValueError("Music AI cue count differs from the source scene count")

        jobs = scenario_goal_jobs(scenario)
        lines = [
            "🎬🎵 Video AI → Music AI 連携完了（制作設計草案）",
            f"作品：{scenario['title']}",
            f"尺：{plan['duration_seconds']}秒 / シーン：{len(scenario['scenes'])}",
            f"音楽キュー：{len(plan['cues'])}件",
            "シナリオのシーンID・感情・同期点をMusic AIへ引き継ぎました。",
            "音源・映像ファイル自体はまだ生成していません。",
        ]
        return AgentResponse(
            text="\\n".join(lines),
            metadata={
                "feature": self.name,
                "status": "online",
                "mode": "video_music_pipeline",
                "handoff": {
                    "from": self.video_agent.name,
                    "to": self.music_agent.name,
                    "scenario_validated": True,
                    "scene_count": len(scenario["scenes"]),
                    "music_cue_count": len(plan["cues"]),
                    "same_scenario_title": True,
                    "duration_match": True,
                },
                "scenario": scenario,
                "music_plan": plan,
                "goal_jobs": jobs,
                "rendering_status": "not_generated",
            },
        )


def run_video_music_pipeline(request: AgentRequest) -> AgentResponse:
    """Convenience entry point for channel adapters and tests."""
    return VideoMusicPipeline().run(request)


def handle_video_request(request: AgentRequest) -> AgentResponse:
    """Normal graph entry point: chain Music AI after scenario requests only.

    Other Video intents retain their existing VideoAgent behavior. This keeps
    storyboard/editing requests from being incorrectly forced through the
    scenario-only handoff while making scenario production an actual route.
    """
    if not isinstance(request, AgentRequest):
        raise TypeError("request must be an AgentRequest")
    if "シナリオ" in request.message.casefold():
        return VideoMusicPipeline().run(request)
    return VideoAgent().handle(request)


__all__ = ["VideoMusicPipeline", "run_video_music_pipeline", "handle_video_request"]
