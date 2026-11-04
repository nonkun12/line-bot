from __future__ import annotations

import json
from pathlib import Path

import pytest

import agents.media.production as production
from agents.video.scenario import build_scenario


def test_production_can_opt_in_to_blender_animatic_and_ffmpeg_mp4(tmp_path, monkeypatch):
    def fake_blender(storyboard, output_dir):
        target = Path(output_dir)
        target.mkdir()
        frames = []
        for index in range(1, len(storyboard["panels"]) + 1):
            frame = target / f"scene_{index:02d}.png"
            frame.write_bytes(b"png")
            frames.append(str(frame))
        return {"status": "rendered", "frame_paths": frames, "frame_count": len(frames)}

    def fake_ffmpeg(edl, scene_media, audio_path, output_path):
        assert set(scene_media) == {"SC01", "SC02", "SC03"}
        assert Path(audio_path).is_file()
        Path(output_path).write_bytes(b"mp4")
        return {"status": "rendered", "path": str(output_path), "format": "MP4"}

    monkeypatch.setattr(production, "render_storyboard_animatic", fake_blender)
    monkeypatch.setattr(production, "render_video_from_edl", fake_ffmpeg)
    result = production.create_audiovisual_production_bundle(
        build_scenario("夜明けの街", duration_seconds=15, scene_count=3),
        tmp_path / "bundle",
        render_animatic=True,
    )

    assert result["video_render_status"] == "rendered"
    assert result["animatic"]["frame_count"] == 3
    assert Path(result["directory"], "final_video.mp4").read_bytes() == b"mp4"
    manifest = json.loads(Path(result["directory"], "manifest.json").read_text())
    assert manifest["artifacts"]["video"] == "final_video.mp4"


def test_production_rejects_two_conflicting_scene_asset_modes(tmp_path):
    with pytest.raises(ValueError, match="not both"):
        production.create_audiovisual_production_bundle(
            build_scenario("夜明けの街", duration_seconds=15, scene_count=3),
            tmp_path / "bundle",
            scene_media={"SC01": "a.png"},
            render_animatic=True,
        )
    assert not (tmp_path / "bundle").exists()
