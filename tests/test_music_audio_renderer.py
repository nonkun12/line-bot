from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.music import audio_renderer


def _inputs(tmp_path):
    midi = tmp_path / "piece.mid"
    midi.write_bytes(b"MThd" + b"\x00" * 20)
    soundfont = tmp_path / "free.sf2"
    soundfont.write_bytes(b"SF2")
    return midi, soundfont


def test_renders_with_explicit_local_assets_and_never_uses_a_shell(tmp_path, monkeypatch):
    midi, soundfont = _inputs(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        output = Path(args[args.index("-F") + 1])
        output.write_bytes(b"RIFF" + b"\x00" * 60)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(audio_renderer.shutil, "which", lambda name: "/usr/bin/fluidsynth")
    monkeypatch.setattr(audio_renderer.subprocess, "run", fake_run)
    output = tmp_path / "rendered.wav"
    result = audio_renderer.render_midi_to_wav(midi, soundfont, output)
    assert result["status"] == "rendered"
    assert output.read_bytes().startswith(b"RIFF")
    args, kwargs = calls[0]
    assert args[0] == "/usr/bin/fluidsynth"
    assert str(soundfont) in args
    assert str(midi.resolve()) in args
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is audio_renderer.subprocess.DEVNULL


def test_missing_fluidsynth_fails_without_creating_output(tmp_path, monkeypatch):
    midi, soundfont = _inputs(tmp_path)
    monkeypatch.setattr(audio_renderer.shutil, "which", lambda _name: None)
    output = tmp_path / "not-created.wav"
    with pytest.raises(RuntimeError, match="not installed"):
        audio_renderer.render_midi_to_wav(midi, soundfont, output)
    assert not output.exists()


def test_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    midi, soundfont = _inputs(tmp_path)
    monkeypatch.setattr(audio_renderer.shutil, "which", lambda _name: "/usr/bin/fluidsynth")
    output = tmp_path / "existing.wav"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        audio_renderer.render_midi_to_wav(midi, soundfont, output)
    assert output.read_bytes() == b"keep"
