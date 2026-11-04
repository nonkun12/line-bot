"""Local FFmpeg assembly for an authored audiovisual EDL.

All media inputs must already exist locally. No assets are downloaded and no
shell is used. This first renderer uses sequential hard cuts; authored
transitions remain in the EDL for later renderer support.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def render_video_from_edl(
    edl: dict[str, Any],
    scene_media: dict[str, str | Path],
    audio_path: str | Path,
    output_path: str | Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Assemble supplied local scene clips/images and WAV music into MP4."""
    if not isinstance(edl, dict) or edl.get("schema_version") != "audiovisual-edl.v1":
        raise ValueError("edl must use audiovisual-edl.v1")
    scenes = edl.get("video_track")
    duration = edl.get("duration_seconds")
    if not isinstance(scenes, list) or not scenes or len(scenes) > 20:
        raise ValueError("EDL must contain 1 to 20 scenes")
    if type(duration) not in (int, float) or not 0 < duration <= 3600:
        raise ValueError("EDL duration is invalid")
    if (
        type(width) is not int or type(height) is not int
        or not (160 <= width <= 3840 and 160 <= height <= 2160)
        or width % 2 or height % 2
    ):
        raise ValueError("width and height must be even integers within supported bounds")
    if type(fps) is not int or not 1 <= fps <= 60:
        raise ValueError("fps must be between 1 and 60")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be between 1 and 1800")
    if any(not isinstance(scene, dict) for scene in scenes):
        raise ValueError("every EDL scene must be an object")
    scene_ids = [scene.get("scene_id") for scene in scenes]
    if (
        any(not isinstance(scene_id, str) or not scene_id.strip() for scene_id in scene_ids)
        or len(set(scene_ids)) != len(scene_ids)
    ):
        raise ValueError("EDL scene IDs must be non-empty and unique")
    if not isinstance(scene_media, dict) or set(scene_media) != set(scene_ids):
        raise ValueError("scene_media must provide exactly one local asset for every EDL scene")

    expected_start = 0.0
    for scene in scenes:
        start = scene.get("start_seconds")
        length = scene.get("duration_seconds")
        if (
            type(start) not in (int, float) or type(length) not in (int, float)
            or start < 0 or length <= 0 or abs(float(start) - expected_start) > 0.001
        ):
            raise ValueError("EDL scene timing is invalid or non-contiguous")
        expected_start = float(start) + float(length)
    if abs(expected_start - float(duration)) > 0.001:
        raise ValueError("EDL scene durations must cover the full timeline")

    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file() or audio.suffix.lower() != ".wav":
        raise ValueError("audio_path must be an existing WAV file")
    inputs = []
    for scene in scenes:
        asset = Path(scene_media[scene["scene_id"]]).expanduser().resolve()
        if not asset.is_file() or asset.suffix.lower() not in _VIDEO_EXTENSIONS | _IMAGE_EXTENSIONS:
            raise ValueError(f"unsupported or missing scene asset: {scene['scene_id']}")
        inputs.append(asset)
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is not installed; no video was rendered")

    output = Path(output_path).expanduser()
    if output.suffix.lower() != ".mp4":
        raise ValueError("output_path must end with .mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(str(output))
    handle = tempfile.NamedTemporaryFile(
        prefix=".ffmpeg-", suffix=".mp4", dir=output.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    args = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for scene, asset in zip(scenes, inputs):
        length = float(scene["duration_seconds"])
        if asset.suffix.lower() in _IMAGE_EXTENSIONS:
            args.extend(["-loop", "1", "-t", f"{length:.6f}", "-i", str(asset)])
        else:
            args.extend(["-i", str(asset)])
    audio_index = len(inputs)
    args.extend(["-i", str(audio)])
    filters = []
    for index, scene in enumerate(scenes):
        length = float(scene["duration_seconds"])
        filters.append(
            f"[{index}:v]trim=duration={length:.6f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1[v{index}]"
        )
    labels = "".join(f"[v{index}]" for index in range(len(scenes)))
    filters.append(f"{labels}concat=n={len(scenes)}:v=1:a=0[vout]")
    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", f"{audio_index}:a:0",
        "-af", f"apad,atrim=duration={float(duration):.6f}",
        "-t", f"{float(duration):.6f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(temporary),
    ])
    try:
        completed = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout_seconds, check=False,
        )
        if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            detail = (completed.stderr or completed.stdout or "FFmpeg produced no video")[-1200:]
            raise RuntimeError(f"FFmpeg video assembly failed: {detail}")
        os.link(temporary, output)
        return {
            "status": "rendered", "path": str(output), "format": "MP4",
            "duration_seconds": duration, "resolution": f"{width}x{height}",
            "fps": fps, "scenes": len(scenes),
            "transition_mode": "sequential_hard_cuts",
            "renderer": "FFmpeg", "bytes": output.stat().st_size,
        }
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["render_video_from_edl"]
