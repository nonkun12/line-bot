from pathlib import Path

from clients.mac_ai_speaker import record_wav


def test_record_wav_rejects_unsafe_duration(tmp_path: Path) -> None:
    try:
        record_wav(tmp_path / "speech.wav", seconds=31)
    except ValueError as exc:
        assert "between 0.5 and 30" in str(exc)
    else:
        raise AssertionError("unsafe duration must be rejected")
