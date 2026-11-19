from pathlib import Path

import pytest

from clients.mac_ai_speaker import record_wav


def test_record_wav_rejects_unsafe_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep this validation test independent of the optional sounddevice package.
    monkeypatch.setattr("clients.mac_ai_speaker.sd", object())

    with pytest.raises(ValueError, match="between 0.5 and 30"):
        record_wav(tmp_path / "speech-short.wav", seconds=0.4)

    with pytest.raises(ValueError, match="between 0.5 and 30"):
        record_wav(tmp_path / "speech-long.wav", seconds=31)
