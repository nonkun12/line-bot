import pytest

from scripts.star_night_game_state import TransitionError, apply_choice
from scripts.star_night_hourly_candidate import build_candidate
from scripts.star_night_hourly_candidate import build_candidate


NODES = [
    {"id": "NODE_START"},
    {"id": "NODE_MEMORY", "unlocks": "LOC_OLD_STATION_ARCHIVE"},
    {"id": "NODE_LIGHTS", "unlocks": "LOC_OLD_STATION_TUNNEL"},
]
STATE = {
    "noa_memory": 0,
    "city_lights": 0,
    "trust_mina": 0,
    "choice_history": [],
    "discovered_locations": [],
}


def test_choice_applies_effect_and_unlocks_target_location_without_mutation():
    choice = {
        "id": "CHOICE_MEMORY",
        "source_node": "NODE_START",
        "effect": {"noa_memory": 1},
        "next_node": "NODE_MEMORY",
    }
    result = apply_choice("NODE_START", STATE, choice, NODES)
    assert result["current_node"] == "NODE_MEMORY"
    assert result["state"]["noa_memory"] == 1
    assert result["state"]["choice_history"] == ["CHOICE_MEMORY"]
    assert result["state"]["discovered_locations"] == ["LOC_OLD_STATION_ARCHIVE"]
    assert STATE["noa_memory"] == 0
    assert STATE["choice_history"] == []


def test_reapplying_unlocked_target_does_not_duplicate_location():
    state = {**STATE, "discovered_locations": ["LOC_OLD_STATION_ARCHIVE"]}
    choice = {
        "id": "CHOICE_MEMORY",
        "source_node": "NODE_START",
        "effect": {"noa_memory": 1},
        "next_node": "NODE_MEMORY",
    }
    result = apply_choice("NODE_START", state, choice, NODES)
    assert result["state"]["discovered_locations"] == ["LOC_OLD_STATION_ARCHIVE"]


@pytest.mark.parametrize(
    ("current", "choice", "nodes", "message"),
    [
        ("NODE_LIGHTS", {"source_node": "NODE_START", "next_node": "NODE_MEMORY", "id": "C"}, NODES, "source"),
        ("NODE_START", {"source_node": "NODE_START", "next_node": "MISSING", "id": "C"}, NODES, "target"),
        ("NODE_START", {"source_node": "NODE_START", "next_node": "NODE_MEMORY", "id": "C", "effect": {"missing": 1}}, NODES, "unknown state"),
        ("NODE_START", {"source_node": "NODE_START", "next_node": "NODE_MEMORY", "id": "C", "effect": {"noa_memory": True}}, NODES, "finite numeric"),
    ],
)
def test_invalid_choices_are_rejected(current, choice, nodes, message):
    with pytest.raises(TransitionError, match=message):
        apply_choice(current, STATE, choice, nodes)


def test_duplicate_node_ids_are_rejected():
    with pytest.raises(TransitionError, match="unique"):
        apply_choice("NODE_START", STATE, {
            "id": "C", "source_node": "NODE_START", "next_node": "NODE_START"
        }, [{"id": "NODE_START"}, {"id": "NODE_START"}])


def test_generated_story_graph_drives_all_three_playable_routes(tmp_path):
    import json

    from scripts.star_night_game_state import apply_choice

    out = tmp_path / "candidate"
    build_candidate(out)
    graph = json.loads((out / "game_story_graph.json").read_text(encoding="utf-8"))
    expected = {
        "CHOICE_LUMINA_01A": ("NODE_MEMORY", "noa_memory", "LOC_OLD_STATION_ARCHIVE"),
        "CHOICE_LUMINA_01B": ("NODE_LIGHTS", "city_lights", "LOC_OLD_STATION_TUNNEL"),
        "CHOICE_LUMINA_01C": ("NODE_TRUST", "trust_mina", "LOC_OLD_STATION_CONTROL"),
    }

    for choice in graph["choices"]:
        target, state_key, location = expected[choice["id"]]
        result = apply_choice(graph["start_node"], graph["initial_state"], choice, graph["nodes"])
        assert result["current_node"] == target
        assert result["state"][state_key] == 1
        assert result["state"]["choice_history"] == [choice["id"]]
        assert result["state"]["discovered_locations"] == [location]

    assert graph["initial_state"] == {"trust_mina": 0, "city_lights": 0, "noa_memory": 0}
