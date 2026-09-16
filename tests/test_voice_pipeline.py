from core.agents import AgentRequest
from core.voice_pipeline import run_voice_pipeline


class FakeSynthesizer:
    name = "fake-tts"

    def synthesize(self, text):
        from core.voice import SpeechResult
        return SpeechResult(
            text=text,
            audio_url="https://example.invalid/audio.mp3",
            mime_type="audio/mpeg",
            provider=self.name,
        )


def test_voice_pipeline_is_channel_neutral(monkeypatch):
    monkeypatch.setattr(
        "core.voice_pipeline.openai_transcribe_audio",
        lambda audio, filename, content_type: "京都の天気を教えて",
    )

    seen = {}

    def core_handler(request: AgentRequest) -> str:
        seen["request"] = request
        return "京都は晴れです。"

    result = run_voice_pipeline(
        b"audio",
        user_id="U1",
        channel="voice",
        core_handler=core_handler,
        synthesizer=FakeSynthesizer(),
    )

    assert result.transcript == "京都の天気を教えて"
    assert result.reply_text == "京都は晴れです。"
    assert result.speech_provider == "fake-tts"
    assert result.speech_available is True
    assert seen["request"].channel == "voice"
    assert seen["request"].metadata["input"] == "voice_audio"


def test_voice_pipeline_fails_closed_when_core_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "core.voice_pipeline.openai_transcribe_audio",
        lambda audio, filename, content_type: "テスト",
    )

    try:
        run_voice_pipeline(
            b"audio",
            user_id="U1",
            channel="voice",
            core_handler=lambda request: "",
        )
    except ValueError as exc:
        assert str(exc) == "voice Core returned empty reply"
    else:
        raise AssertionError("expected empty Core reply to fail closed")
