"""Video specialist agent with a structured scenario-first workflow."""
from __future__ import annotations

from agents.video.intents import is_video_intent
from agents.video.scenario import build_scenario
from agents.video.storyboard import build_storyboard
from agents.video.shot_list import build_shot_list
from agents.video.edit_decision_list import build_edit_decision_list
from core.agents import AgentRequest, AgentResponse


class VideoAgent:
    name = "video"
    description = "Scenario-first video planning, scripting, storyboarding, shot design, and editing plans."
    priority = 84
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_video_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        text = request.message.casefold()
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        if any(k in text for k in ("シナリオ", "scenario", "台本", "脚本", "script")):
            mode = "scenario" if any(k in text for k in ("シナリオ", "scenario")) else "script"
            try:
                scenario = metadata.get("scenario")
                if not isinstance(scenario, dict):
                    scenario = build_scenario(
                        request.message,
                        duration_seconds=metadata.get("duration_seconds", 180),
                        scene_count=metadata.get("scene_count", 4),
                        genre=metadata.get("genre", "未指定"),
                        audience=metadata.get("target_audience", "一般視聴者"),
                        tone=metadata.get("tone", "わかりやすく、印象に残る"),
                        premise=metadata.get("premise"),
                        title=metadata.get("title"),
                    )
                storyboard = build_storyboard(scenario)
                shot_list = build_shot_list(storyboard)
                music_plan = metadata.get("music_plan")
                edl = build_edit_decision_list(scenario, music_plan) if isinstance(music_plan, dict) else None
            except ValueError as exc:
                return AgentResponse(
                    text=f"シナリオを作成できませんでした。尺・シーン数・入力内容を確認してください：{exc}",
                    metadata={"feature": self.name, "status": "invalid_request", "mode": mode},
                )
            lines = [
                f"🎬 映像AI｜シナリオ草案：{scenario['title']}",
                f"尺：{scenario['creative_brief']['duration_seconds']}秒 / "
                f"シーン数：{len(scenario['scenes'])}",
                "状態：草案（台詞・演出の詳細化とレビュー前）",
                "",
            ]
            for scene in scenario["scenes"]:
                lines.extend([
                    f"{scene['scene_id']}｜{scene['act_label']}｜"
                    f"{scene['time_start_seconds']}秒〜"
                    f"{scene['time_start_seconds'] + scene['duration_seconds']}秒",
                    f"目的：{scene['purpose']}",
                    f"展開：{scene['story_beat']}",
                    f"映像：{scene['visual_direction']}",
                    "",
                ])
            lines.append("次工程：脚本詳細化 → 連続性レビュー → 絵コンテ → ショットリスト → 音響設計")
            lines.append(f"絵コンテ：{len(storyboard['panels'])}パネル / ショット設計：{len(shot_list['shots'])}カット（いずれも編集可能な草案）")
            if edl is not None:
                lines.append("音楽設計と同期した映像編集タイムライン（EDL）も作成しました。実際の映像書き出しは未実施です。")
            reply = "\n".join(lines)
            return AgentResponse(
                text=reply,
                metadata={
                    "feature": self.name, "status": "online", "mode": mode,
                    "scenario": scenario,
                    "storyboard": storyboard,
                    "shot_list": shot_list,
                    "next_artifacts": scenario["next_artifacts"],
                    "edit_decision_list": edl,
                },
            )
        if any(k in text for k in ("絵コンテ", "storyboard", "ショット")):
            mode = "storyboard"
            reply = "🎬 まず承認済みシナリオを基準に、各シーンの絵コンテとショット構成を設計します。"
        elif any(k in text for k in ("編集", "カット", "字幕")):
            mode = "editing"
            reply = (
                "🎬 映像AIを起動しました。\n\n"
                "シナリオと絵コンテを基準に、カット、字幕、BGM、トランジションを設計します。\n"
                "動画ファイルの実編集・書き出し・配信連携はまだ接続していません。"
            )
        else:
            mode = "video_planning"
            reply = (
                "🎬 映像AIを起動しました。\n\n"
                "最初に企画とシナリオを固め、その後に絵コンテ、ショット、音響、映像制作へ進みます。\n"
                "動画の実生成・書き出し連携は後段で接続します。"
            )
        return AgentResponse(text=reply, metadata={"feature": self.name, "status": "online", "mode": mode})


agent = VideoAgent()
