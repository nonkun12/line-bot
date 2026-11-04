import wave
import io

import pytest

from agents.music.score_plan import build_music_plan
from agents.music.wav_renderer import build_wav_bytes, write_wav_file
from agents.video.scenario import build_scenario


def _plan():
    return build_music_plan(build_scenario(
        "A quiet town discovers a new light",
        duration_seconds=12,
        scene_count=3,
    ))


def test_renders_original_cues_as_valid_pcm_wav():
    data = build_wav_bytes(_plan(), bpm=96)
    with wave.open(io.BytesIO(data), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == 22050
        assert reader.getnframes() == 12 * 22050
        assert reader.readframes(10)


def test_wav_writer_never_overwrites_existing_file(tmp_path):
    path = tmp_path / "preview.wav"
    result = write_wav_file(_plan(), path)
    assert result["status"] == "generated"
    assert path.read_bytes().startswith(b"RIFF")
    with pytest.raises(FileExistsError):
        write_wav_file(_plan(), path)


def test_rejects_unsupported_duration_and_invalid_cue():
    plan = _plan()
    plan["duration_seconds"] = 91
    with pytest.raises(ValueError, match="duration_seconds"):
        build_wav_bytes(plan)
    plan = _plan()
    plan["cues"][0]["energy"] = "extreme"
    with pytest.raises(ValueError, match="invalid timing"):
        build_wav_bytes(plan)
