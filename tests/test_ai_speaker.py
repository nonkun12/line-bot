from core.ai_speaker import AISpeaker, SpeakerRequest, SpeakerResponse


class FakeBrain:
    def __init__(self) -> None:
        self.requests: list[SpeakerRequest] = []

    def respond(self, request: SpeakerRequest) -> SpeakerResponse:
        self.requests.append(request)
        return SpeakerResponse(f"reply: {request.text}", request.session_id)


def test_ai_speaker_normalizes_transcript_and_preserves_session() -> None:
    brain = FakeBrain()
    speaker = AISpeaker(brain)

    result = speaker.handle_transcript("  東京の天気は？  ", session_id="session-1")

    assert result == SpeakerResponse("reply: 東京の天気は？", "session-1")
    assert brain.requests == [SpeakerRequest("東京の天気は？", "session-1")]


def test_ai_speaker_rejects_empty_transcript() -> None:
    brain = FakeBrain()
    speaker = AISpeaker(brain)

    try:
        speaker.handle_transcript("  ")
    except ValueError as exc:
        assert str(exc) == "speech transcript must not be empty"
    else:
        raise AssertionError("empty transcript must fail closed")
