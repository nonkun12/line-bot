from datetime import datetime, timezone
import json
import wave

import pytest

from scripts import star_night_hourly_candidate as candidate_builder
from scripts.star_night_hourly_candidate import build_candidate


def test_candidate_contains_editable_story_and_game_assets(tmp_path):
    out = tmp_path / "candidate"
    result = build_candidate(out, now=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc))
    assert result["status"] == "candidate_created"
    scenario = json.loads((out / "scenario.json").read_text())
    assert len(scenario["scenes"]) == 5
    assert sum(scene["duration"] for scene in scenario["scenes"]) == 15
    assert (out / "screenplay.md").is_file()
    assert (out / "storyboard.json").is_file()
    assert (out / "shot_list.json").is_file()
    assert (out / "game_story_graph.json").is_file()
    critic = json.loads((out / "critic_review.json").read_text())
    assert critic["status"] == "PASS"
    assert all(critic["checks"].values())
    graph = json.loads((out / "game_story_graph.json").read_text())
    node_ids = {node["id"] for node in graph["nodes"]}
    assert len(node_ids) == 4
    assert graph["start_node"] == "NODE_START"
    assert all(choice["source_node"] in node_ids and choice["next_node"] in node_ids for choice in graph["choices"])
    assert critic["checks"]["graph_reachability_valid"] is True
    assert all(set(choice["effect"]).issubset(graph["initial_state"]) for choice in graph["choices"])


def test_candidate_generates_original_midi_and_valid_wav(tmp_path):
    out = tmp_path / "candidate"
    build_candidate(out)
    midi = (out / "original_music.mid").read_bytes()
    assert midi.startswith(b"MThd")
    with wave.open(str(out / "original_music.wav"), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 22050
        assert wav.getnframes() == 15 * 22050


def test_hourly_focus_rotates_and_requires_review(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    a = build_candidate(first, now=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc))
    b = build_candidate(second, now=datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc))
    assert a["task_focus"] != b["task_focus"]
    task = json.loads((second / "hourly_task.json").read_text())
    assert task["requires_critic_and_human_approval"] is True


def test_existing_output_is_never_overwritten(tmp_path):
    out = tmp_path / "candidate"
    build_candidate(out)
    with pytest.raises(FileExistsError):
        build_candidate(out)


def test_cloud_animatic_renders_video_and_includes_music(tmp_path):
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")
    pytest.importorskip("PIL")
    out = tmp_path / "candidate"
    result = build_candidate(out, render_animatic=True)
    video = out / "star-night-episode-01-animatic.mp4"
    assert video.is_file()
    assert video.stat().st_size > 10_000
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["video_render_status"] == "motion_animatic_rendered"
    assert manifest["motion_profile"]["camera"] == "per-shot slow pan and 4.5% zoom"
    assert manifest["motion_profile"]["character_animation"] is False
    assert "star-night-episode-01-animatic.mp4" in manifest["sha256"]
    assert result["video"] == str(video)


def test_critic_fails_when_structural_check_fails(tmp_path, monkeypatch):
    invalid_scenes = [dict(scene) for scene in candidate_builder.SCENES]
    invalid_scenes[1]["id"] = invalid_scenes[0]["id"]
    monkeypatch.setattr(candidate_builder, "SCENES", invalid_scenes)

    out = tmp_path / "invalid-candidate"
    build_candidate(out)
    critic = json.loads((out / "critic_review.json").read_text())
    assert critic["status"] == "FAIL"
    assert critic["checks"]["five_unique_scene_ids"] is False


def test_each_hourly_focus_creates_a_distinct_deliverable(tmp_path):
    from datetime import timedelta

    expected = {
        "continuity": "continuity_sheet.json",
        "episode_002": "episode_002_outline.json",
        "branch_graph": "branch_reachability.json",
        "visual_design": "visual_design.json",
        "music_variation": "music_variations.json",
        "game_loop": "game_loop_design.json",
    }
    start = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)
    seen = set()
    for offset in range(6):
        out = tmp_path / f"hour-{offset}"
        result = build_candidate(out, now=start + timedelta(hours=offset))
        focus = result["task_focus"]
        assert focus in expected
        artifact = out / expected[focus]
        assert artifact.is_file()
        payload = json.loads(artifact.read_text())
        assert payload["focus_id"] == focus
        seen.add(focus)
    assert seen == set(expected)



def test_branch_graph_declares_every_choice_target(tmp_path):
    filename, artifact = candidate_builder._build_hourly_focus_artifact("branch_graph")
    node_ids = {node["id"] for node in artifact["nodes"]}
    assert filename == "branch_reachability.json"
    assert len(node_ids) == 4
    assert artifact["start_node"] == "NODE_START"
    assert all(branch["source_node"] in node_ids and branch["next_node"] in node_ids for branch in artifact["branches"])
    assert artifact["reachability"]["all_nodes_reachable"] is True
    assert artifact["reachability"]["unreachable_nodes"] == []


def test_graph_reachability_uses_traversal_and_detects_unreachable_nodes():
    analyze = candidate_builder._analyze_reachability
    nodes = [{"id": "START"}, {"id": "A"}, {"id": "B"}, {"id": "ORPHAN"}]
    edges = [
        {"id": "to-a", "source_node": "START", "next_node": "A"},
        {"id": "to-b", "source_node": "A", "next_node": "B"},
    ]
    result = analyze("START", nodes, edges)
    assert result["reachable_nodes"] == ["A", "B", "START"]
    assert result["unreachable_nodes"] == ["ORPHAN"]
    assert result["all_nodes_reachable"] is False


def test_graph_reachability_rejects_undeclared_edge_endpoints():
    result = candidate_builder._analyze_reachability(
        "START",
        [{"id": "START"}],
        [{"id": "broken", "source_node": "START", "next_node": "MISSING"}],
    )
    assert result["invalid_edges"] == ["broken"]
    assert result["all_nodes_reachable"] is False


def test_graph_reachability_handles_cycles_without_looping():
    result = candidate_builder._analyze_reachability(
        "START",
        [{"id": "START"}, {"id": "A"}],
        [
            {"id": "forward", "source_node": "START", "next_node": "A"},
            {"id": "back", "source_node": "A", "next_node": "START"},
        ],
    )
    assert result["all_nodes_reachable"] is True
    assert result["reachable_nodes"] == ["A", "START"]
