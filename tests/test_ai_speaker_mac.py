from core.ai_speaker import AISpeaker, SpeakerResponse
from core.ai_speaker_mac import MacSpeakerAdapter


class FakeBrain:
    def respond(self, request):
        return SpeakerResponse(f"reply: {request.text}", request.session_id)


def test_mac_adapter_sends_core_response_to_speech_output() -> None:
    spoken: list[str] = []
    adapter = MacSpeakerAdapter(AISpeaker(FakeBrain()), speak=spoken.append)

    result = adapter.handle_transcript("  こんにちは  ", session_id="mac-1")

    assert result == SpeakerResponse("reply: こんにちは", "mac-1")
    assert spoken == ["reply: こんにちは"]
