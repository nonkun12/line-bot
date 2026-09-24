"""Music specialist agent foundation."""
from __future__ import annotations

from core.agents import AgentRequest, AgentResponse
from agents.music.intents import is_music_intent
from agents.music.provider import UnconfiguredMusicProvider, build_composition_request


class MusicAgent:
    name = "music"
    def __init__(self, provider=None) -> None:
        self.provider = provider or UnconfiguredMusicProvider()
    description = "Music planning, recommendations, original composition support, and playlist design."
    priority = 84
    enabled = True

    def can_handle(self, request: AgentRequest) -> bool:
        return is_music_intent(request.message)

    def handle(self, request: AgentRequest) -> AgentResponse:
        text = request.message.casefold()
        result = None
        if any(k in text for k in ("作曲", "作詞", "メロディ", "楽曲制作")):
            mode = "composition"
            result = self.provider.compose(build_composition_request(request.message))
            reply = (
                "🎵 音楽AIを起動しました。\n\n"
                "オリジナル楽曲の企画・作曲/作詞補助・構成設計を行います。\n"
                "ジャンル / 雰囲気 / テンポ / 楽器 / 曲の長さを指定できます。\n"
                f"生成状態: {result.status}（provider: {result.provider}）\n"
                f"{result.message}"
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
            metadata={
                "feature": self.name,
                "status": "online",
                "mode": mode,
                **({
                    "generation_status": result.status,
                    "provider": result.provider,
                } if result is not None else {}),
            },
        )


agent = MusicAgent()
