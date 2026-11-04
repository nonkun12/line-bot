"""Bounded, dependency-free signal analysis for local audiovisual drafts.

Audio: WAV PCM16 window features. Video: FFmpeg samples low-resolution RGB frames.
No files are modified; subprocesses use fixed arguments, no shell, and strict bounds.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any


_MAX_SECONDS = 90
_AUDIO_WINDOW_SECONDS = 0.5
_VIDEO_SAMPLE_FPS = 1
_VIDEO_WIDTH = 64
_VIDEO_HEIGHT = 36
_MAX_VIDEO_FRAMES = 90


def _db(value: float) -> float:
    return round(20.0 * math.log10(max(value, 1e-7)), 2)


def analyze_wav_signal(
    audio_path: str | Path,
    *,
    window_seconds: float = _AUDIO_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Extract per-window loudness, peak, zero-crossing rate and spectral centroid."""
    path = Path(audio_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".wav":
        raise ValueError("audio_path must be an existing WAV file")
    if type(window_seconds) not in (int, float) or not 0.1 <= window_seconds <= 2.0:
        raise ValueError("window_seconds must be between 0.1 and 2.0")
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        rate = reader.getframerate()
        frames = reader.getnframes()
        if channels not in (1, 2) or width != 2 or rate < 8000:
            raise ValueError("audio must be mono/stereo PCM16 at 8kHz or higher")
        duration = frames / rate
        if not 0 < duration <= _MAX_SECONDS:
            raise ValueError(f"audio duration must be within 1..{_MAX_SECONDS} seconds")
        raw = reader.readframes(frames)
    frame_count = len(raw) // (2 * channels)
    if frame_count != frames:
        raise ValueError("WAV frame data is truncated")

    def mono_sample(index: int) -> float:
        offset = index * channels * 2
        left = int.from_bytes(raw[offset:offset + 2], "little", signed=True)
        if channels == 2:
            right = int.from_bytes(raw[offset + 2:offset + 4], "little", signed=True)
            left = (left + right) // 2
        return left / 32768.0

    window_frames = max(1, int(rate * float(window_seconds)))
    windows = []
    for first in range(0, frames, window_frames):
        last = min(frames, first + window_frames)
        step = max(1, (last - first) // 2048)
        samples = [mono_sample(i) for i in range(first, last, step)]
        if not samples:
            continue
        rms = math.sqrt(sum(value * value for value in samples) / len(samples))
        peak = max(abs(value) for value in samples)
        crossings = sum(
            1 for left, right in zip(samples, samples[1:])
            if (left < 0 <= right) or (right < 0 <= left)
        )
        zcr = crossings / max(1, len(samples) - 1)

        # A small direct DFT is sufficient for a coarse brightness indicator.
        fft_samples = samples[:256]
        if len(fft_samples) < 16:
            centroid_hz = 0.0
        else:
            magnitudes = []
            for bin_index in range(1, 65):
                real = imag = 0.0
                for sample_index, sample in enumerate(fft_samples):
                    angle = 2.0 * math.pi * bin_index * sample_index / len(fft_samples)
                    real += sample * math.cos(angle)
                    imag -= sample * math.sin(angle)
                magnitudes.append((bin_index * rate / len(fft_samples), math.hypot(real, imag)))
            magnitude_sum = sum(magnitude for _, magnitude in magnitudes)
            centroid_hz = (
                sum(freq * magnitude for freq, magnitude in magnitudes) / magnitude_sum
                if magnitude_sum else 0.0
            )
        windows.append({
            "start_seconds": round(first / rate, 3),
            "end_seconds": round(last / rate, 3),
            "rms_dbfs": _db(rms),
            "peak_dbfs": _db(peak),
            "zero_crossing_rate": round(zcr, 4),
            "spectral_centroid_hz": round(centroid_hz, 1),
        })
    return {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "audio",
        "duration_seconds": round(duration, 3),
        "sample_rate": rate,
        "channels": channels,
        "window_seconds": float(window_seconds),
        "windows": windows,
        "limitations": ["Synthetic and musical timbre can affect spectral centroid.", "Features do not establish musical quality or emotional meaning."],
    }


def _frame_metrics(frame: bytes) -> dict[str, float]:
    pixels = len(frame) // 3
    luma_sum = saturation_sum = 0.0
    for offset in range(0, len(frame), 3):
        red, green, blue = frame[offset], frame[offset + 1], frame[offset + 2]
        luma_sum += 0.2126 * red + 0.7152 * green + 0.0722 * blue
        saturation_sum += max(red, green, blue) - min(red, green, blue)
    return {
        "mean_luma": round(luma_sum / pixels, 2),
        "mean_saturation": round(saturation_sum / pixels, 2),
    }


def analyze_video_signal(
    video_path: str | Path,
    *,
    ffmpeg_executable: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Sample at most 90 low-resolution frames and report luminance/color/motion."""
    path = Path(video_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise ValueError("video_path must be an existing supported video file")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be between 1 and 120")
    executable = ffmpeg_executable or shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("FFmpeg is not installed")
    args = [
        executable, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-vf",
        f"fps={_VIDEO_SAMPLE_FPS},scale={_VIDEO_WIDTH}:{_VIDEO_HEIGHT}",
        "-frames:v", str(_MAX_VIDEO_FRAMES), "-f", "rawvideo",
        "-pix_fmt", "rgb24", "pipe:1",
    ]
    completed = subprocess.run(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout_seconds, check=False,
    )
    frame_bytes = _VIDEO_WIDTH * _VIDEO_HEIGHT * 3
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace")[-800:]
        raise RuntimeError(f"FFmpeg video analysis failed: {detail}")
    if not completed.stdout or len(completed.stdout) > frame_bytes * _MAX_VIDEO_FRAMES:
        raise RuntimeError("FFmpeg returned no frames or exceeded the analysis bound")
    if len(completed.stdout) % frame_bytes:
        raise RuntimeError("FFmpeg returned an incomplete RGB frame")
    frames = [
        completed.stdout[offset:offset + frame_bytes]
        for offset in range(0, len(completed.stdout), frame_bytes)
    ]
    samples = []
    previous_luma = None
    for index, frame in enumerate(frames):
        metrics = _frame_metrics(frame)
        motion = 0.0
        if previous_luma is not None:
            previous = previous_luma
            current = metrics["mean_luma"]
            motion = round(abs(current - previous), 2)
        metrics.update({"at_seconds": index, "frame_change_luma": motion})
        samples.append(metrics)
        previous_luma = metrics["mean_luma"]
    return {
        "schema_version": "audiovisual-signal-analysis.v1",
        "media_type": "video",
        "sample_fps": _VIDEO_SAMPLE_FPS,
        "sample_width": _VIDEO_WIDTH,
        "sample_height": _VIDEO_HEIGHT,
        "samples": samples,
        "limitations": ["One frame per second at 64x36 is a coarse visual proxy.", "Frame-change luminance does not detect semantic scene changes or artistic quality."],
    }


def compare_scene_signals(
    audio_report: dict[str, Any],
    video_report: dict[str, Any],
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate measurable signal features within each authored scene interval."""
    if audio_report.get("schema_version") != "audiovisual-signal-analysis.v1" or audio_report.get("media_type") != "audio":
        raise ValueError("audio_report must be an audio signal analysis")
    if video_report.get("schema_version") != "audiovisual-signal-analysis.v1" or video_report.get("media_type") != "video":
        raise ValueError("video_report must be a video signal analysis")
    results = []
    for scene in scenes:
        start = scene.get("start_seconds", scene.get("time_start_seconds"))\n        end = scene.get("end_seconds")\n        if end is None and type(start) in (int, float) and type(scene.get("duration_seconds")) in (int, float):\n            end = start + scene["duration_seconds"]
        if type(start) not in (int, float) or type(end) not in (int, float) or start < 0 or end <= start:
            raise ValueError("scene intervals must have valid start_seconds and end_seconds")
        audio = [
            item for item in audio_report["windows"]
            if item["start_seconds"] < end and item["end_seconds"] > start
        ]
        video = [
            item for item in video_report["samples"]
            if start <= item["at_seconds"] < end
        ]
        results.append({
            "scene_id": scene.get("scene_id"),
            "start_seconds": start,
            "end_seconds": end,
            "audio_window_count": len(audio),
            "audio_mean_rms_dbfs": round(sum(item["rms_dbfs"] for item in audio) / len(audio), 2) if audio else None,
            "audio_mean_spectral_centroid_hz": round(sum(item["spectral_centroid_hz"] for item in audio) / len(audio), 1) if audio else None,
            "video_sample_count": len(video),
            "video_mean_luma": round(sum(item["mean_luma"] for item in video) / len(video), 2) if video else None,
            "video_mean_saturation": round(sum(item["mean_saturation"] for item in video) / len(video), 2) if video else None,
            "video_mean_frame_change_luma": round(sum(item["frame_change_luma"] for item in video) / len(video), 2) if video else None,
        })
    return {
        "schema_version": "audiovisual-scene-signal-report.v1",
        "scene_count": len(results),
        "scenes": results,
        "interpretation": "Measured signal features only; no automatic inference of emotion, story meaning, or artistic quality.",
    }


__all__ = ["analyze_wav_signal", "analyze_video_signal", "compare_scene_signals"]
