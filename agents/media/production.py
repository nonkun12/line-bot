"""Local, free-tool audiovisual artifact bundle creation.

The bundle includes an editable scenario, music plan, original MIDI, a
dependency-free synthesized WAV preview, and synchronized video EDL. When
local scene assets are supplied, FFmpeg can assemble a draft MP4. Nothing is
downloaded and existing output directories are never overwritten.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from agents.music.audio_renderer import render_midi_to_wav
from agents.music.midi_composer import write_midi_file
from agents.music.score_plan import build_music_plan
from agents.music.wav_renderer import write_wav_file
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.ffmpeg_renderer import render_video_from_edl
from agents.video.scenario import validate_scenario


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def create_audiovisual_production_bundle(
    scenario: dict[str, Any],
    output_dir: str | Path,
    *,
    bpm: int = 120,
    genre: str = "映像に合わせたオリジナル音楽",
    instrumentation: str = "映像の世界観に合う編成",
    soundfont_path: str | Path | None = None,
    scene_media: dict[str, str | Path] | None = None,
    audio_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a new local bundle. output_dir must be a new, exact directory."""
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))
    music_plan = build_music_plan(scenario, genre=genre, instrumentation=instrumentation)
    edl = build_edit_decision_list(scenario, music_plan)
    destination = Path(output_dir).expanduser()
    if not destination.name or destination.name in {".", ".."}:
        raise ValueError("output_dir must name a new bundle directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)

    try:
        _write_json_exclusive(destination / "scenario.json", scenario)
        _write_json_exclusive(destination / "music_plan.json", music_plan)
        _write_json_exclusive(destination / "edit_decision_list.json", edl)
        midi = write_midi_file(music_plan, destination / "original_music.mid", bpm=bpm)
        if soundfont_path is None:
            preview_plan = copy.deepcopy(music_plan)
            preview_duration = min(preview_plan["duration_seconds"], 90)
            if preview_duration < preview_plan["duration_seconds"]:
                preview_plan["duration_seconds"] = preview_duration
                clipped_cues = []
                for cue in preview_plan["cues"]:
                    if cue["start_seconds"] >= preview_duration:
                        continue
                    cue["end_seconds"] = min(cue["end_seconds"], preview_duration)
                    cue["sync_points"] = [
                        point for point in cue.get("sync_points", [])
                        if point.get("at_seconds", 0) <= preview_duration
                    ]
                    clipped_cues.append(cue)
                preview_plan["cues"] = clipped_cues
            audio = write_wav_file(preview_plan, destination / "original_music.wav", bpm=bpm)
            audio_status = (
                "synthesized_preview" if preview_duration == music_plan["duration_seconds"]
                else "synthesized_preview_first_90_seconds"
            )
        else:
            audio = render_midi_to_wav(
                destination / "original_music.mid",
                soundfont_path,
                destination / "original_music.wav",
            )
            preview_duration = music_plan["duration_seconds"]
            audio_status = "rendered"

        selected_audio = Path(audio_path).expanduser() if audio_path is not None else destination / "original_music.wav"
        video = None
        if scene_media is not None:
            if audio_path is None and preview_duration < music_plan["duration_seconds"]:
                raise ValueError(
                    "video rendering needs a full-length WAV; provide audio_path or a soundfont renderer"
                )
            video = render_video_from_edl(
                edl, scene_media, selected_audio, destination / "final_video.mp4"
            )

        artifacts = {
            "scenario": "scenario.json",
            "music_plan": "music_plan.json",
            "midi": "original_music.mid",
            "audio_preview": "original_music.wav",
            "video_edit_decision_list": "edit_decision_list.json",
        }
        if video is not None:
            artifacts["video"] = "final_video.mp4"
        manifest = {
            "schema_version": "audiovisual-production-bundle.v1",
            "status": "draft",
            "title": scenario["title"],
            "artifacts": artifacts,
            "midi": midi,
            "audio_preview": audio,
            "audio_render_status": audio_status,
            "audio_preview_duration_seconds": preview_duration,
            "video_render_status": "rendered" if video else "not_rendered",
            "video": video,
            "external_assets_attached": scene_media is not None,
            "rights_review_required_before_publication": True,
        }
        _write_json_exclusive(destination / "manifest.json", manifest)
    except Exception:
        # Remove only files created inside this newly-created bundle directory.
        for child in destination.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        destination.rmdir()
        raise

    return {
        "status": "draft_bundle_created",
        "directory": str(destination),
        "artifacts": manifest["artifacts"],
        "midi": midi,
        "audio_render_status": audio_status,
        "audio_preview": audio,
        "video": video,
        "video_render_status": manifest["video_render_status"],
    }


__all__ = ["create_audiovisual_production_bundle"]
