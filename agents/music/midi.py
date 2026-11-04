"""Dependency-free Standard MIDI File generation for original audiovisual cues.

The generated file is a compact piano sketch, not a rendered audio recording.
It uses only Python's standard library so local/cloud execution stays free.
"""
from __future__ import annotations

import base64
import math
import struct
from typing import Any

_TICKS_PER_QUARTER = 480
_BPM = 96
_TICKS_PER_SECOND = _TICKS_PER_QUARTER * _BPM / 60
_MOTIF = (60, 64, 67, 72, 71, 67, 64, 62)
_CHORDS = ((48, 52, 55), (43, 47, 50), (45, 48, 52), (41, 45, 48))
_ENERGY_NOTES = {"low": 2, "medium": 4, "high": 8}


def _vlq(value: int) -> bytes:
    """Encode a non-negative MIDI variable-length quantity."""
    if value < 0:
        raise ValueError("MIDI delta time cannot be negative")
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
        value >>= 7
    encoded = bytearray()
    while True:
        encoded.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            return bytes(encoded)


def _tick(seconds: int | float) -> int:
    return round(float(seconds) * _TICKS_PER_SECOND)


def build_midi_bytes(music_plan: dict[str, Any]) -> bytes:
    """Render a validated cue plan to a single-track type-0 MIDI byte string."""
    if not isinstance(music_plan, dict):
        raise ValueError("music_plan must be an object")
    cues = music_plan.get("cues")
    duration = music_plan.get("duration_seconds")
    if type(duration) is not int or duration <= 0 or not isinstance(cues, list) or not cues:
        raise ValueError("music plan requires positive duration and non-empty cues")

    events: list[tuple[int, int, bytes]] = []
    # 96 BPM, 4/4, acoustic grand piano.
    events.append((0, 0, b"\xff\x51\x03" + (60_000_000 // _BPM).to_bytes(3, "big")))
    events.append((0, 1, b"\xff\x58\x04\x04\x02\x18\x08"))
    events.append((0, 2, b"\xc0\x00"))

    previous_end = 0
    for cue_index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("each music cue must be an object")
        start = cue.get("start_seconds")
        end = cue.get("end_seconds")
        energy = cue.get("energy")
        if (
            type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end)
            or start < previous_end or end <= start or end > duration
            or not isinstance(energy, str) or energy not in _ENERGY_NOTES
        ):
            raise ValueError(f"invalid timing or energy in cue {cue_index + 1}")
        scene_id = cue.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id.strip():
            raise ValueError(f"scene_id missing in cue {cue_index + 1}")
        previous_end = end
        start_tick, end_tick = _tick(start), _tick(end)
        span = end_tick - start_tick
        if span < 2:
            raise ValueError("cue is too short to contain a MIDI note")

        chord = _CHORDS[cue_index % len(_CHORDS)]
        velocity = {"low": 42, "medium": 62, "high": 82}[energy]
        # Sustained harmony establishes the scene's emotional bed.
        for note in chord:
            events.append((start_tick, 4, bytes((0x90, note, max(1, velocity - 18)))))
            events.append((end_tick, 3, bytes((0x80, note, 0))))

        count = _ENERGY_NOTES[energy]
        for step in range(count):
            note_start = start_tick + (span * step // count)
            note_end = start_tick + (span * (step + 1) // count)
            if note_end <= note_start:
                continue
            motif_note = _MOTIF[(cue_index * 2 + step) % len(_MOTIF)]
            # A little register lift at the climax, while retaining the motif.
            if energy == "high":
                motif_note += 12
            note_velocity = min(120, velocity + (5 if step in (0, count - 1) else 0))
            events.append((note_start, 5, bytes((0x90, motif_note, note_velocity))))
            events.append((note_end, 2, bytes((0x80, motif_note, 0))))

    events.sort(key=lambda item: (item[0], item[1]))
    track = bytearray()
    last_tick = 0
    for tick, _priority, payload in events:
        track.extend(_vlq(tick - last_tick))
        track.extend(payload)
        last_tick = tick
    track.extend(b"\x00\xff\x2f\x00")
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, _TICKS_PER_QUARTER)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def build_wav_preview_bytes(music_plan: dict[str, Any], *, max_seconds: int = 15) -> bytes:
    """Render a short, dependency-free synthesized preview (not a production mix).

    The preview intentionally uses a simple sine-wave piano-like timbre. It is
    bounded to 15 seconds and 11.025 kHz mono so API payloads and CPU remain small.
    """
    import wave
    from array import array

    if type(max_seconds) is not int or not 1 <= max_seconds <= 15:
        raise ValueError("max_seconds must be between 1 and 15")
    # Reuse MIDI validation so both artifacts accept exactly the same score.
    build_midi_bytes(music_plan)
    sample_rate = 11025
    duration = min(float(music_plan["duration_seconds"]), float(max_seconds))
    frame_count = int(duration * sample_rate)
    mix = [0.0] * frame_count
    cues = music_plan["cues"]

    def add_note(note: int, start: float, end: float, velocity: int) -> None:
        start = max(0.0, float(start))
        end = min(duration, float(end))
        first = max(0, int(start * sample_rate))
        last = min(frame_count, int(end * sample_rate))
        if last <= first:
            return
        frequency = 440.0 * (2.0 ** ((note - 69) / 12.0))
        amplitude = (velocity / 127.0) * 0.11
        length = last - first
        attack = max(1, int(0.012 * sample_rate))
        release = max(1, int(0.08 * sample_rate))
        for index in range(length):
            remaining = length - index
            envelope = min(1.0, index / attack, remaining / release)
            t = (first + index) / sample_rate
            # Fundamental plus a quiet second harmonic for a soft bell/piano tint.
            sample = math.sin(2.0 * math.pi * frequency * t)
            sample += 0.18 * math.sin(4.0 * math.pi * frequency * t)
            mix[first + index] += sample * amplitude * max(0.0, envelope)

    motif = _MOTIF
    for cue_index, cue in enumerate(cues):
        start = float(cue["start_seconds"])
        end = min(float(cue["end_seconds"]), duration)
        if start >= duration:
            continue
        velocity = {"low": 42, "medium": 62, "high": 82}[cue["energy"]]
        for note in _CHORDS[cue_index % len(_CHORDS)]:
            add_note(note, start, end, max(1, velocity - 18))
        count = _ENERGY_NOTES[cue["energy"]]
        span = float(cue["end_seconds"]) - float(cue["start_seconds"])
        for step in range(count):
            note_start = start + span * step / count
            note_end = start + span * (step + 1) / count
            note = motif[(cue_index * 2 + step) % len(motif)]
            if cue["energy"] == "high":
                note += 12
            add_note(note, note_start, note_end, min(120, velocity + (5 if step in (0, count - 1) else 0)))

    pcm = array("h", (int(max(-1.0, min(1.0, value)) * 32767) for value in mix))
    if __import__("sys").byteorder != "little":
        pcm.byteswap()
    output = __import__("io").BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


def build_midi_artifact(music_plan: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe base64 MIDI artifact for a LINE/API response."""
    midi = build_midi_bytes(music_plan)
    preview_wav = build_wav_preview_bytes(music_plan)
    title = str(music_plan.get("source_scenario_title") or "audiovisual-score")
    safe_title = "".join(ch for ch in title if ch.isalnum() or ch in "-_")[:40] or "audiovisual-score"
    return {
        "filename": f"{safe_title}.mid",
        "mime_type": "audio/midi",
        "encoding": "base64",
        "content_base64": base64.b64encode(midi).decode("ascii"),
        "size_bytes": len(midi),
        "preview_audio": {
            "filename": f"{safe_title}-preview.wav",
            "mime_type": "audio/wav",
            "encoding": "base64",
            "content_base64": base64.b64encode(preview_wav).decode("ascii"),
            "size_bytes": len(preview_wav),
            "duration_seconds": min(music_plan["duration_seconds"], 15),
            "sample_rate_hz": 11025,
            "channels": 1,
            "status": "short_synthesized_preview",
            "limitations": "15秒以内の簡易合成プレビューです。完成音源・実楽器音源・最終ミックスではありません。",
        },
        "duration_seconds": music_plan["duration_seconds"],
        "status": "generated_midi_sketch",
        "limitations": "MIDI演奏データです。音声ファイルではなく、再生にはMIDI音源が必要です。",
    }


__all__ = ["build_midi_bytes", "build_wav_preview_bytes", "build_midi_artifact"]
