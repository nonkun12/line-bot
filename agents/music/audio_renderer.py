"""Optional local MIDI-to-WAV rendering through free FluidSynth.

No binary, soundfont, or audio asset is downloaded. The caller must supply an
existing local SF2/SF3 soundfont and MIDI file.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def render_midi_to_wav(
    midi_path: str | Path,
    soundfont_path: str | Path,
    output_path: str | Path,
    *,
    sample_rate: int = 44100,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Render a MIDI file with a locally installed FluidSynth executable."""
    midi = Path(midi_path).expanduser().resolve()
    soundfont = Path(soundfont_path).expanduser().resolve()
    output = Path(output_path).expanduser()
    if not midi.is_file() or midi.suffix.lower() != ".mid":
        raise ValueError("midi_path must be an existing .mid file")
    if not soundfont.is_file() or soundfont.suffix.lower() not in {".sf2", ".sf3"}:
        raise ValueError("soundfont_path must be an existing .sf2 or .sf3 file")
    if type(sample_rate) is not int or not 22050 <= sample_rate <= 96000:
        raise ValueError("sample_rate must be between 22050 and 96000")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise ValueError("timeout_seconds must be between 1 and 600")
    executable = shutil.which("fluidsynth")
    if executable is None:
        raise RuntimeError("FluidSynth is not installed; no audio was rendered")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(str(output))

    handle = tempfile.NamedTemporaryFile(
        prefix=".fluidsynth-", suffix=".wav", dir=output.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        completed = subprocess.run(
            [
                executable,
                "-ni",
                "-F", str(temporary),
                "-r", str(sample_rate),
                str(soundfont),
                str(midi),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 44:
            detail = (completed.stderr or completed.stdout or "FluidSynth produced no audio")[-1000:]
            raise RuntimeError(f"FluidSynth rendering failed: {detail}")
        # Hard-link creation is atomic and fails if the destination appeared
        # during rendering; never replace a user's existing audio file.
        os.link(temporary, output)
        return {
            "status": "rendered",
            "path": str(output),
            "format": "WAV",
            "sample_rate": sample_rate,
            "bytes": output.stat().st_size,
            "renderer": "FluidSynth",
        }
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["render_midi_to_wav"]
