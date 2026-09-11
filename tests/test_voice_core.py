from core.voice import DisabledSpeechSynthesizer, SpeechResult, build_speech_result


def test_disabled_speech_synthesizer_is_safe_default():
    result = DisabledSpeechSynthesizer().synthesize("こんにちは")

    assert result == SpeechResult(text="こんにちは", provider="none")
    assert not result.available


def test_build_speech_result_uses_backend():
    class FakeSynthesizer:
        name = "test"

        def synthesize(self, text):
            return SpeechResult(text=text, audio_url="https://example.test/a.mp3", mime_type="audio/mpeg", provider=self.name)

    result = build_speech_result("hello", FakeSynthesizer())

    assert result.text == "hello"
    assert result.audio_url == "https://example.test/a.mp3"
    assert result.mime_type == "audio/mpeg"
    assert result.provider == "test"
    assert result.available


def test_build_speech_result_degrades_when_backend_fails():
    class BrokenSynthesizer:
        name = "broken"

        def synthesize(self, text):
            raise RuntimeError("provider unavailable")

    result = build_speech_result("hello", BrokenSynthesizer())

    assert result == SpeechResult(text="hello", provider="none")
    assert not result.available
