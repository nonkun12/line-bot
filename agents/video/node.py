"""Video specialist agent foundation."""
from __future__ import annotations

from core.agents import AgentRequest, AgentResponse

_VIDEO_KEYWORDS = (
    "動画", "映像", "video", "movie", "ショート動画", "youtube",
    "ユーチューブ", "編集", "絵コンテ", "台本", "動画制作",
)


class VideoAgent:
    name = "video"
    description = "Video planning, scripting, storyboarding, shot design, and editing plans."
    priority = 84
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        text = request.message.casefold()
        return any(keyword.casefold() in text for keyword in _VIDEO_KEYWORDS)

    def handle(self, request: AgentRequest) -> AgentResponse:
        text = request.message.casefold()
        if any(k in text for k in ("台本", "script", "脚本")):
            mode = "script"
            reply = (
                "🎬 映像AIを起動しました。\n\n"
                "動画台本を、目的・尺・視聴者・構成に合わせて設計します。"
            )
        elif any(k in text for k in ("絵コンテ", "storyboard", "ショット")):
            mode = "storyboard"
            reply = (
                "🎬 映像AIを起動しました。\n\n"
                "絵コンテ、ショットリスト、カット構成を設計します。"
            )
        elif any(k in text for k in ("編集", "カット", "字幕")):
            mode = "editing"
            reply = (
                "🎬 映像AIを起動しました。\n\n"
                "カット、字幕、BGM、トランジションなどの編集設計を支援します。\n"
                "動画ファイルの実編集・書き出し・配信連携はまだ接続していません。"
            )
        else:
            mode = "video_planning"
            reply = (
                "🎬 映像AIを起動しました。\n\n"
                "動画企画、構成、台本、絵コンテ、編集方針を支援します。\n"
                "動画の実生成・書き出し連携は後段で接続します。"
            )

        return AgentResponse(
            text=reply,
            metadata={"feature": self.name, "status": "online", "mode": mode},
        )


agent = VideoAgent()
