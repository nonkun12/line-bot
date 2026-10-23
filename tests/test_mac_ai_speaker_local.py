from pathlib import Path

import pytest

from clients.mac_ai_speaker_local import ask_local_ollama, record_wav, validate_seconds


@pytest.mark.parametrize("seconds", [0, 0.49, 30.01, 60])
def test_validate_seconds_rejects_out_of_range(seconds: float) -> None:
    with pytest.raises(ValueError, match="between 0.5 and 30"):
        validate_seconds(seconds)


@pytest.mark.parametrize("seconds", [0.5, 1, 30])
def test_validate_seconds_accepts_boundary(seconds: float) -> None:
    validate_seconds(seconds)


def test_record_wav_validates_before_optional_dependency(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 0.5 and 30"):
        record_wav(tmp_path / "invalid.wav", seconds=0.4)


def test_local_ollama_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="message is required"):
        ask_local_ollama("   ")
