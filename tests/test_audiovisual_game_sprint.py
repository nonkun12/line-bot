import pytest

from agents.media.audiovisual_game_sprint import build_audiovisual_game_sprint_plan


def test_builds_full_story_to_game_dependency_chain():
    plan = build_audiovisual_game_sprint_plan("goal-001", "Create a short audiovisual story that becomes a playable game.")

    assert plan["schema_version"] == "audiovisual-to-game-sprint-plan.v1"
    assert plan["dependency_order"][0] == "scenario"
    assert plan["dependency_order"][-1] == "game_test"
    by_id = {item["job_id"]: item for item in plan["stages"]}
    assert "scenario" in by_id["music"]["depends_on"]
    assert {"music", "visual"}.issubset(set(by_id["sync"]["depends_on"]))
    assert "decision" in by_id["godot_design"]["depends_on"]
    assert plan["safety_policy"]["automatic_merge"] is False
    assert plan["safety_policy"]["paid_services_required"] is False


def test_revision_iteration_cap_is_enforced():
    with pytest.raises(ValueError, match="between 1 and 3"):
        build_audiovisual_game_sprint_plan("goal-001", "Build a game", max_revision_iterations=4)


def test_only_supported_platforms_are_accepted():
    with pytest.raises(ValueError, match="target_platform"):
        build_audiovisual_game_sprint_plan("goal-001", "Build a game", target_platform="mobile")


def test_goal_and_objective_are_validated():
    with pytest.raises(ValueError, match="goal_id"):
        build_audiovisual_game_sprint_plan("../unsafe", "Build a game")
    with pytest.raises(ValueError, match="objective"):
        build_audiovisual_game_sprint_plan("goal-001", "")
