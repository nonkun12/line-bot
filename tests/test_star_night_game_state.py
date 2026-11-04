import pytest

from scripts.star_night_game_state import TransitionError, apply_choice


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
