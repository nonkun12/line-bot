"""Local, free-tool audiovisual artifact bundle creation.

The bundle contains an editable MIDI composition sketch, its scenario-aware
music cue plan, the screenplay/scenario draft, and a synchronized video EDL.
It does not claim to render audio or video and performs no network operations.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.music.midi_composer import write_midi_file
from agents.music.audio_renderer import render_midi_to_wav
from agents.music.score_plan import build_music_plan
from agents.video.edit_decision_list import build_edit_decision_list
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
) -> dict[str, Any]:
    """Create a new, non-overwriting local production bundle.

    output_dir is the exact new bundle directory, not a parent directory.
    Existing directories are rejected to prevent accidental replacement.
    """
    errors = validate_scenario(scenario)
    if errors:
        raise ValueError("invalid scenario: " + ", ".join(errors))
    music_plan = build_music_plan(
        scenario, genre=genre, instrumentation=instrumentation
    )
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
        audio = None
        if soundfont_path is not None:
            audio = render_midi_to_wav(
                destination / "original_music.mid",
                soundfont_path,
                destination / "original_music.wav",
            )
        manifest = {
            "schema_version": "audiovisual-production-bundle.v1",
            "status": "draft",
            "title": scenario["title"],
            "artifacts": {
                "scenario": "scenario.json",
                "music_plan": "music_plan.json",
                "midi": "original_music.mid",
                "video_edit_decision_list": "edit_decision_list.json",
            },
            "midi": midi,
            "audio_render_status": "not_rendered",
            "video_render_status": "not_rendered",
            "external_assets_attached": False,
            "rights_review_required_before_publication": True,
        }
        _write_json_exclusive(destination / "manifest.json", manifest)
    except Exception:
        # Only remove the newly-created bundle directory; never touch an
        # existing user directory or any path outside this exact directory.
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
        "audio_render_status": manifest["audio_render_status"],
        "audio": audio,
        "video_render_status": manifest["video_render_status"],
    }


__all__ = ["create_audiovisual_production_bundle"]
