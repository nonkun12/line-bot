"""Music specialist agent foundation."""
from __future__ import annotations

import base64

from core.agents import AgentRequest, AgentResponse
from agents.music.intents import is_music_intent
from agents.music.score_plan import build_music_plan
from agents.music.midi_composer import build_midi_bytes


class MusicAgent:
    name = "music"
    description = "Music planning, recommendations, original composition support, and playlist design."
    priority = 84
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_music_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        text = request.message.casefold()
        scenario = request.metadata.get("scenario") if isinstance(request.metadata, dict) else None
        if isinstance(scenario, dict):
            try:
                plan = build_music_plan(
                    scenario,
                    genre=request.metadata.get("music_genre", "映像に合わせたオリジナル音楽"),
                    instrumentation=request.metadata.get("instrumentation", "映像の世界観に合う編成"),
                )
            except ValueError as exc:
                return AgentResponse(
                    text=f"音楽設計を作成できませんでした。シナリオまたは設定を確認してください：{exc}",
                    metadata={"feature": self.name, "status": "invalid_request", "mode": "audiovisual_score_plan"},
                )
            try:
                midi_bytes = build_midi_bytes(plan, bpm=request.metadata.get("bpm", 120))
            except ValueError as exc:
                return AgentResponse(
                    text=f"MIDIスケッチを生成できませんでした。テンポまたは音楽設計を確認してください：{exc}",
                    metadata={"feature": self.name, "status": "invalid_request", "mode": "audiovisual_score_plan"},
                )
            midi_base64 = base64.b64encode(midi_bytes).decode("ascii")
            line_break = chr(10)
            return AgentResponse(
                text=(
                    f"🎵 映像連動の音楽設計：{plan['source_scenario_title']}{line_break}"
                    f"尺：{plan['duration_seconds']}秒 / キュー：{len(plan['cues'])}件{line_break}"
                    "シナリオの感情曲線・シーン時刻・同期点からオリジナルMIDIスケッチを生成しました。"
                    "4トラックのStandard MIDI Fileです。音源へのレンダリングは別工程です。"
                ),
                metadata={
                    "feature": self.name, "status": "online",
                    "mode": "audiovisual_score_plan", "music_plan": plan,
                    "midi_artifact": {
                        "filename": "original-audiovisual-score.mid",
                        "mime_type": "audio/midi",
                        "encoding": "base64",
                        "content": midi_base64,
                        "bytes": len(midi_bytes),
                        "tracks": 4,
                        "bpm": request.metadata.get("bpm", 120),
                        "status": "generated",
                    },
                },
            )
        if any(k in text for k in ("作曲", "作詞", "メロディ", "楽曲制作")):
            mode = "composition"
            reply = (
                "🎵 音楽AIを起動しました。\n\n"
                "オリジナル楽曲の企画・作曲/作詞補助・構成設計を行います。\n"
                "ジャンル / 雰囲気 / テンポ / 楽器 / 曲の長さを指定できます。"
            )
        elif any(k in text for k in ("playlist", "プレイリスト", "選曲")):
            mode = "playlist"
            reply = (
                "🎵 音楽AIを起動しました。\n\n"
                "用途・気分・ジャンル・時間に合わせたプレイリストを設計します。\n"
                "実際の音源再生・配信連携はまだ接続していません。"
            )
        else:
            mode = "music_planning"
            reply = (
                "🎵 音楽AIを起動しました。\n\n"
                "音楽の企画、選曲、楽曲アイデア、BGM設計を支援します。\n"
                "実際の音源生成・再生連携は後段で接続します。"
            )

        return AgentResponse(
            text=reply,
            metadata={"feature": self.name, "status": "online", "mode": mode},
        )


agent = MusicAgent()
