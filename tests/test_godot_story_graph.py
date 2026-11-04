from copy import deepcopy

import pytest

from agents.media.godot_story_graph import build_story_graph, resolve_story_transition


def branching_scenes():
    return [
        {
            "scene_id": "opening",
            "story_intent": "The player reaches a fork in the forest.",
            "choices": [
                {"choice_id": "left", "label": "Follow the river", "next_scene_id": "river"},
                {"choice_id": "right", "label": "Climb the hill", "next_scene_id": "hill"},
            ],
        },
        {"scene_id": "river", "story_intent": "A quiet river reveals a clue.", "next_scene_id": "ending"},
        {"scene_id": "hill", "story_intent": "A high view reveals the same clue.", "next_scene_id": "ending"},
        {"scene_id": "ending", "story_intent": "The paths converge.", "ending": True},
    ]


def test_builds_reachable_branching_graph_and_preserves_all_routes():
    graph = build_story_graph(branching_scenes())
    assert graph["schema_version"] == "godot-story-graph.v1"
    assert graph["entry_scene_id"] == "opening"
    assert graph["scene_count"] == 4
    assert [item["next_scene_id"] for item in graph["scenes"][0]["choices"]] == ["river", "hill"]


def test_resolves_each_player_choice_without_mutating_graph():
    graph = build_story_graph(branching_scenes())
    before = deepcopy(graph)
    assert resolve_story_transition(graph, "opening", "left") == {
        "status": "CHOICE_SELECTED",
        "from_scene_id": "opening",
        "choice_id": "left",
        "next_scene_id": "river",
    }
    assert resolve_story_transition(graph, "opening", "right")["next_scene_id"] == "hill"
    assert graph == before


def test_multiple_choices_require_explicit_choice_id():
    graph = build_story_graph(branching_scenes())
    with pytest.raises(ValueError, match="choice_id is required"):
        resolve_story_transition(graph, "opening")


def test_single_choice_can_be_resolved_without_choice_id():
    scenes = [
        {"scene_id": "start", "story_intent": "Start", "choices": [
            {"choice_id": "continue", "label": "Continue", "next_scene_id": "end"}
        ]},
        {"scene_id": "end", "story_intent": "End", "ending": True},
    ]
    graph = build_story_graph(scenes)
    assert resolve_story_transition(graph, "start")["next_scene_id"] == "end"


def test_linear_transition_and_ending():
    graph = build_story_graph([
        {"scene_id": "start", "story_intent": "Start", "next_scene_id": "end"},
        {"scene_id": "end", "story_intent": "End", "ending": True},
    ])
    assert resolve_story_transition(graph, "start")["status"] == "ADVANCE"
    assert resolve_story_transition(graph, "end")["status"] == "ENDING"


@pytest.mark.parametrize("mutate", [
    lambda scenes: scenes[0].update(scene_id="../escape"),
    lambda scenes: scenes[0].update(choices=[{"choice_id": "x", "label": "Go", "next_scene_id": "missing"}]),
    lambda scenes: scenes[0].update(choices=[
        {"choice_id": "x", "label": "Go", "next_scene_id": "river"},
        {"choice_id": "x", "label": "Again", "next_scene_id": "hill"},
    ]),
    lambda scenes: scenes[0].update(choices=[{"choice_id": "x", "label": "", "next_scene_id": "river"}]),
    lambda scenes: scenes[0].update(choices=[
        {"choice_id": str(i), "label": "Go", "next_scene_id": "river"} for i in range(5)
    ]),
    lambda scenes: scenes[0].update(ending=True),
])
def test_rejects_invalid_graphs(mutate):
    scenes = branching_scenes()
    mutate(scenes)
    with pytest.raises(ValueError):
        build_story_graph(scenes)


def test_rejects_unreachable_scenes():
    scenes = branching_scenes()
    scenes.append({"scene_id": "orphan", "story_intent": "Not reachable", "ending": True})
    with pytest.raises(ValueError, match="unreachable"):
        build_story_graph(scenes)


def test_allows_intentional_cycles_when_all_scenes_are_reachable():
    graph = build_story_graph([
        {"scene_id": "start", "story_intent": "Start", "next_scene_id": "loop"},
        {"scene_id": "loop", "story_intent": "Loop", "choices": [
            {"choice_id": "again", "label": "Try again", "next_scene_id": "loop"},
            {"choice_id": "finish", "label": "Finish", "next_scene_id": "end"},
        ]},
        {"scene_id": "end", "story_intent": "End", "ending": True},
    ])
    assert resolve_story_transition(graph, "loop", "again")["next_scene_id"] == "loop"


def test_rejects_unknown_current_scene_and_choice():
    graph = build_story_graph(branching_scenes())
    with pytest.raises(ValueError):
        resolve_story_transition(graph, "missing")
    with pytest.raises(ValueError):
        resolve_story_transition(graph, "opening", "unknown")
