import json
from pathlib import Path

import pytest

from agents.media.production import create_audiovisual_production_bundle
from agents.video.scenario import build_scenario


def _scenario():
    return build_scenario(
        "A small journey from uncertainty to hope",
        duration_seconds=30,
        scene_count=3,
    )


def test_creates_complete_editable_music_and_video_production_bundle(tmp_path):
    destination = tmp_path / "作品01"
    result = create_audiovisual_production_bundle(_scenario(), destination, bpm=96)
    assert result["status"] == "draft_bundle_created"
    assert (destination / "scenario.json").is_file()
    assert (destination / "music_plan.json").is_file()
    assert (destination / "edit_decision_list.json").is_file()
    assert (destination / "original_music.mid").read_bytes().startswith(b"MThd")
    assert (destination / "original_music.wav").read_bytes().startswith(b"RIFF")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["audio_render_status"] == "synthesized_preview"
    assert manifest["audio_preview"]["format"] == "WAV PCM 16-bit stereo"
    assert manifest["video_render_status"] == "not_rendered"
    edl = json.loads((destination / "edit_decision_list.json").read_text(encoding="utf-8"))
    assert edl["schema_version"] == "audiovisual-edl.v1"
    assert len(edl["video_track"]) == len(edl["audio_track"]) == 3


def test_refuses_to_overwrite_an_existing_bundle(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_audiovisual_production_bundle(_scenario(), destination)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_invalid_scenario_does_not_create_output_directory(tmp_path):
    destination = tmp_path / "invalid"
    with pytest.raises(ValueError, match="invalid scenario"):
        create_audiovisual_production_bundle({}, destination)
    assert not destination.exists()


def test_bundle_can_render_wav_when_local_soundfont_is_supplied(tmp_path, monkeypatch):
    from agents.media import production

    def fake_render(midi_path, soundfont_path, output_path, **kwargs):
        assert Path(midi_path).is_file()
        assert Path(soundfont_path).is_file()
        Path(output_path).write_bytes(b"RIFF" + b"\x00" * 64)
        return {"status": "rendered", "path": str(output_path), "format": "WAV"}

    soundfont = tmp_path / "free.sf2"
    soundfont.write_bytes(b"SF2")
    monkeypatch.setattr(production, "render_midi_to_wav", fake_render)
    destination = tmp_path / "rendered-bundle"
    result = production.create_audiovisual_production_bundle(
        _scenario(), destination, soundfont_path=soundfont
    )
    assert result["audio_render_status"] == "rendered"
    assert (destination / "original_music.wav").read_bytes().startswith(b"RIFF")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["audio_render_status"] == "rendered"


def test_bundle_can_assemble_video_when_local_scene_assets_are_supplied(tmp_path, monkeypatch):
    from agents.media import production

    scenario = _scenario()
    scene_media = {}
    for scene in scenario["scenes"]:
        asset = tmp_path / f"{scene['scene_id']}.mp4"
        asset.write_bytes(b"video")
        scene_media[scene["scene_id"]] = asset

    def fake_render(edl, media, audio_path, output_path, **kwargs):
        assert len(edl["video_track"]) == 3
        assert set(media) == set(scene_media)
        assert Path(audio_path).is_file()
        Path(output_path).write_bytes(b"MP4")
        return {"status": "rendered", "path": str(output_path), "format": "MP4"}

    monkeypatch.setattr(production, "render_video_from_edl", fake_render)
    destination = tmp_path / "video-bundle"
    result = production.create_audiovisual_production_bundle(
        scenario, destination, scene_media=scene_media
    )
    assert result["video_render_status"] == "rendered"
    assert (destination / "final_video.mp4").read_bytes() == b"MP4"
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["video"] == "final_video.mp4"
    assert manifest["video_render_status"] == "rendered"
