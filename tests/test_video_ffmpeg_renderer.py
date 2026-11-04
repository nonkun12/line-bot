from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.music.score_plan import build_music_plan
from agents.video.ffmpeg_renderer import _camera_motion_filter, render_video_from_edl
from agents.video.edit_decision_list import build_edit_decision_list
from agents.video.scenario import build_scenario


def _inputs(tmp_path):
    scenario = build_scenario("A new day begins", duration_seconds=30, scene_count=3)
    edl = build_edit_decision_list(scenario, build_music_plan(scenario))
    assets = {}
    for scene in scenario["scenes"]:
        asset = tmp_path / f"{scene['scene_id']}.mp4"
        asset.write_bytes(b"video")
        assets[scene["scene_id"]] = asset
    audio = tmp_path / "music.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 60)
    return edl, assets, audio


def test_assembles_local_assets_with_ffmpeg_without_shell_or_overwrite(tmp_path, monkeypatch):
    edl, assets, audio = _inputs(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[-1]).write_bytes(b"mp4-data")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("agents.video.ffmpeg_renderer.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("agents.video.ffmpeg_renderer.subprocess.run", fake_run)
    output = tmp_path / "final.mp4"
    result = render_video_from_edl(edl, assets, audio, output, width=640, height=360, fps=24)
    assert result["status"] == "rendered"
    assert result["transition_mode"] == "sequential_hard_cuts"
    assert result["sync_edit_plan"]["schema_version"] == "audiovisual-sync-edit-plan.v1"
    assert result["sync_edit_plan"]["event_count"] == len(edl["sync_events"])
    assert all(item["automatic_cut"] is False for item in result["sync_edit_plan"]["suggestions"])
    assert output.read_bytes() == b"mp4-data"
    args, kwargs = calls[0]
    assert args[0] == "/usr/bin/ffmpeg"
    assert "-filter_complex" in args
    filter_graph = args[args.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=0" in filter_graph
    assert "zoompan=" in filter_graph
    assert "min(1+on*0.12/" in filter_graph
    assert kwargs["stdin"] is __import__("subprocess").DEVNULL
    assert "shell" not in kwargs
    with pytest.raises(FileExistsError):
        render_video_from_edl(edl, assets, audio, output)


def test_supports_still_images_and_rejects_missing_scene_assets(tmp_path, monkeypatch):
    edl, assets, audio = _inputs(tmp_path)
    image = tmp_path / "still.png"
    image.write_bytes(b"image")
    assets[edl["video_track"][0]["scene_id"]] = image
    monkeypatch.setattr("agents.video.ffmpeg_renderer.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        "agents.video.ffmpeg_renderer.subprocess.run",
        lambda args, **kwargs: (Path(args[-1]).write_bytes(b"mp4"), SimpleNamespace(returncode=0, stderr="", stdout=""))[1],
    )
    result = render_video_from_edl(edl, assets, audio, tmp_path / "stills.mp4")
    assert result["status"] == "rendered"

    incomplete = dict(assets)
    incomplete.pop(edl["video_track"][-1]["scene_id"])
    with pytest.raises(ValueError, match="exactly one local asset"):
        render_video_from_edl(edl, incomplete, audio, tmp_path / "missing.mp4")


def test_rejects_noncontiguous_or_malformed_scenes_before_rendering(tmp_path, monkeypatch):
    edl, assets, audio = _inputs(tmp_path)
    broken = dict(edl)
    broken["video_track"] = [None]
    with pytest.raises(ValueError, match="every EDL scene"):
        render_video_from_edl(broken, assets, audio, tmp_path / "bad.mp4")
    broken = dict(edl)
    broken["video_track"] = [dict(item) for item in edl["video_track"]]
    broken["video_track"][1]["start_seconds"] += 1
    with pytest.raises(ValueError, match="non-contiguous"):
        render_video_from_edl(broken, assets, audio, tmp_path / "bad2.mp4")


def test_requires_local_ffmpeg_and_wav_audio(tmp_path, monkeypatch):
    edl, assets, audio = _inputs(tmp_path)
    monkeypatch.setattr("agents.video.ffmpeg_renderer.shutil.which", lambda _name: None)
    with pytest.raises(RuntimeError, match="FFmpeg is not installed"):
        render_video_from_edl(edl, assets, audio, tmp_path / "no-ffmpeg.mp4")
    with pytest.raises(ValueError, match="WAV"):
        render_video_from_edl(edl, assets, tmp_path / "not-audio.mp3", tmp_path / "bad.mp4")

def test_camera_motion_filter_uses_only_fixed_allowlisted_expressions():
    push = _camera_motion_filter("slow_push_in", 10, 30, 640, 360)
    pull = _camera_motion_filter("slow_pull_back", 10, 30, 640, 360)
    reveal = _camera_motion_filter("decisive_reveal", 10, 30, 640, 360)
    fallback = _camera_motion_filter("untrusted-expression", 10, 30, 640, 360)
    assert r"\," in push and "min(" in push
    assert r"\," in pull and "max(" in pull
    assert r"\," in reveal and "min(" in reveal
    assert "untrusted-expression" not in fallback
    assert "zoompan=z='1.0'" in fallback
