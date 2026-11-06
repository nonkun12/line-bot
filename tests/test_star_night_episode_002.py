import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAR_NIGHT = ROOT / "docs" / "creative-worlds" / "star-night"


def load_json(name):
    return json.loads((STAR_NIGHT / name).read_text(encoding="utf-8"))


def test_episode_002_timeline_is_contiguous_and_27_seconds():
    episode = load_json("episode-002.json")
    scenes = episode["scenes"]
    assert [scene["id"] for scene in scenes] == ["SC01", "SC02", "SC03", "SC04", "SC05"]
    assert scenes[0]["start"] == 0
    for current, following in zip(scenes, scenes[1:]):
        assert current["start"] + current["duration"] == following["start"]
    assert sum(scene["duration"] for scene in scenes) == 27
    assert scenes[-1]["start"] + scenes[-1]["duration"] == episode["duration_seconds"]


def test_episode_002_has_three_unique_exclusive_choices():
    episode = load_json("episode-002.json")
    choice_scene = next(scene for scene in episode["scenes"] if scene["id"] == "SC04")
    choices = choice_scene["choices"]
    assert choice_scene["choice_id"] == "CHOICE_E002"
    assert choice_scene["exclusive"] is True
    assert [choice["id"] for choice in choices] == [
        "CHOICE_E002_MEMORY",
        "CHOICE_E002_LIGHTS",
        "CHOICE_E002_TRUST",
    ]
    assert len({choice["id"] for choice in choices}) == len(choices)
    assert {tuple(choice["effect"]) for choice in choices} == {
        ("noa_memory",), ("city_lights",), ("trust_mina",)
    }
    assert len({choice["unlock"] for choice in choices}) == 3


def test_episode_002_graph_connects_all_entries_and_converges():
    graph = load_json("game-story-graph.json")
    nodes = {node["id"]: node for node in graph["nodes"]}
    for entry in ("SN_E002_MEMORY", "SN_E002_STATION", "SN_E002_WORKSHOP"):
        assert nodes[entry]["next"] == "SN_E002_SC01"
    assert nodes["SN_E002_SC01"]["next"] == "SN_E002_SC02"
    assert nodes["SN_E002_SC02"]["next"] == "SN_E002_SC03"
    assert nodes["SN_E002_SC03"]["next"] == "SN_E002_SC04"

    choice = nodes["SN_E002_SC04"]
    assert {option["id"] for option in choice["options"]} == {
        "CHOICE_E002_MEMORY", "CHOICE_E002_LIGHTS", "CHOICE_E002_TRUST"
    }
    for option in choice["options"]:
        assert option["next"] in nodes
        assert nodes[option["next"]]["next"] == "SN_E002_SC05"
    assert nodes["SN_E002_SC05"]["event_id"] == "EVENT_UNKNOWN_BLACKOUT_001"


def test_episode_002_critic_is_pending_and_cannot_change_canon():
    review = load_json("episode-002-independent-review.json")
    assert review["status"] == "PENDING_INDEPENDENT_REVIEW"
    assert review["canon_change"] is False
    assert review["publication_authorized"] is False
    assert len(review["reviewers"]) == 3
    assert all("independence" in reviewer for reviewer in review["reviewers"])


def test_project_registers_episode_002_assets():
    project = load_json("project.json")
    assert "docs/creative-worlds/star-night/episode-002.md" in project["episode_refs"]
    assert "docs/creative-worlds/star-night/episode-002.json" in project["episode_data_refs"]
