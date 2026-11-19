from core.voice_contract import VoiceInput, VoiceText, as_ai_request


def test_voice_input_is_provider_neutral():
    request = VoiceInput(audio=b"audio", mime_type="audio/ogg", metadata={"duration_ms": 1200})
    assert request.audio == b"audio"
    assert request.mime_type == "audio/ogg"
    assert request.metadata["duration_ms"] == 1200


def test_voice_text_maps_into_common_gateway_request():
    speech = VoiceText("天気を教えて", confidence=0.98, metadata={"locale": "ja-JP"})
    request = as_ai_request("Uvoice", speech, metadata={"source": "ios"})
    assert request.user_id == "Uvoice"
    assert request.message == "天気を教えて"
    assert request.channel == "voice"
    assert request.metadata == {"locale": "ja-JP", "source": "ios"}
