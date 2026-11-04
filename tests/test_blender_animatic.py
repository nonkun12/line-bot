from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import agents.video.blender_animatic as renderer
from agents.video.scenario import build_scenario
from agents.video.storyboard import build_storyboard


def _storyboard():
    return build_storyboard(build_scenario("夜明けの街", duration_seconds=15, scene_count=3))


def test_blender_animatic_uses_fixed_background_invocation_and_returns_frames(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        destination = Path(args[args.index("--") + 2])
        for index in range(1, 4):
            (destination / f"scene_{index:02d}.png").write_bytes(b"png-frame")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(renderer.shutil, "which", lambda name: "/Applications/Blender")
    monkeypatch.setattr(renderer.subprocess, "run", fake_run)
    result = renderer.render_storyboard_animatic(_storyboard(), tmp_path / "frames")

    assert result["frame_count"] == 3
    assert result["visual_mode"] == "procedural_storyboard_blocking"
    assert result["final_animation"] is False
    args, kwargs = calls[0]
    assert args[:3] == ["/Applications/Blender", "--background", "--factory-startup"]
    assert kwargs["shell"] if "shell" in kwargs else True
    assert kwargs["timeout"] == 900


def test_blender_animatic_fails_closed_when_blender_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Blender is not installed"):
        renderer.render_storyboard_animatic(_storyboard(), tmp_path / "frames")
    assert not (tmp_path / "frames").exists()


def test_blender_animatic_rejects_existing_output_and_invalid_storyboard(tmp_path, monkeypatch):
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(FileExistsError):
        renderer.render_storyboard_animatic(_storyboard(), target, blender_executable="/blender")
    invalid = {"schema_version": "wrong", "panels": []}
    with pytest.raises(ValueError, match="video-storyboard.v1"):
        renderer.render_storyboard_animatic(invalid, tmp_path / "invalid", blender_executable="/blender")

def test_blender_animatic_rejects_non_contiguous_timeline(tmp_path, monkeypatch):
    storyboard = _storyboard()
    storyboard["panels"][1]["time_start_seconds"] += 1
    monkeypatch.setattr(renderer.shutil, "which", lambda name: "/Applications/Blender")
    with pytest.raises(ValueError, match="contiguous"):
        renderer.render_storyboard_animatic(storyboard, tmp_path / "frames")
    assert not (tmp_path / "frames").exists()

def test_blender_script_includes_wrapped_narration_and_optional_japanese_font():
    assert "wrap_caption" in renderer._BLENDER_SCRIPT
    assert "dialogue_or_narration" in renderer._BLENDER_SCRIPT
    assert "NotoSansCJK-Regular.ttc" in renderer._BLENDER_SCRIPT
    assert "ヒラギノ角ゴシック" in renderer._BLENDER_SCRIPT
