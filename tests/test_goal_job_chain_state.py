import pytest

from agents.media.goal_job_chain_state import derive_goal_job_chain_state


def plan():
    return {
        "schema_version": "audiovisual-to-game-sprint-plan.v1",
        "goal_id": "film-game-01",
        "stages": [
            {"job_id": "scenario", "depends_on": [], "human_gate": "scenario_review"},
            {"job_id": "music", "depends_on": ["scenario"], "human_gate": "listening_review"},
            {"job_id": "visual", "depends_on": ["scenario"], "human_gate": "visual_review"},
            {"job_id": "sync", "depends_on": ["music", "visual"], "human_gate": None},
            {"job_id": "game", "depends_on": ["sync"], "human_gate": "playtest"},
        ],
    }


def test_initial_goal_chain_exposes_only_root_job_as_ready():
    result = derive_goal_job_chain_state(plan())
    assert result["ready_job_ids"] == ["scenario"]
    assert result["state"]["music"] == "BLOCKED"
    assert result["permissions"]["execute_jobs"] is False


def test_human_gate_blocks_dependents_until_explicit_approval():
    result = derive_goal_job_chain_state(plan(), completed_job_ids=["scenario"])
    assert result["state"]["scenario"] == "AWAITING_HUMAN_APPROVAL"
    assert result["ready_job_ids"] == []

    approved = derive_goal_job_chain_state(
        plan(),
        completed_job_ids=["scenario"],
        approved_gate_job_ids=["scenario"],
    )
    assert approved["ready_job_ids"] == ["music", "visual"]


def test_parallel_branches_join_only_after_both_are_approved():
    result = derive_goal_job_chain_state(
        plan(),
        completed_job_ids=["scenario", "music", "visual"],
        approved_gate_job_ids=["scenario", "music", "visual"],
    )
    assert result["ready_job_ids"] == ["sync"]
    result = derive_goal_job_chain_state(
        plan(),
        completed_job_ids=["scenario", "music", "visual", "sync"],
        approved_gate_job_ids=["scenario", "music", "visual"],
    )
    assert result["ready_job_ids"] == ["game"]


def test_hold_propagates_to_all_downstream_jobs():
    result = derive_goal_job_chain_state(plan(), held_job_ids=["visual"])
    assert result["state"]["visual"] == "HOLD"
    assert result["state"]["sync"] == "HOLD"
    assert result["state"]["game"] == "HOLD"
    assert result["ready_job_ids"] == ["scenario"]


def test_snapshot_is_deterministic_and_resume_inputs_are_explicit():
    first = derive_goal_job_chain_state(
        plan(),
        completed_job_ids=["scenario"],
        approved_gate_job_ids=["scenario"],
    )
    resumed = derive_goal_job_chain_state(
        plan(),
        completed_job_ids=first["snapshot"]["completed_job_ids"],
        approved_gate_job_ids=first["snapshot"]["approved_gate_job_ids"],
        held_job_ids=first["snapshot"]["held_job_ids"],
    )
    assert resumed == first


@pytest.mark.parametrize(
    "kwargs",
    [
        {"completed_job_ids": ["missing"]},
        {"approved_gate_job_ids": ["scenario"]},
        {"completed_job_ids": ["scenario"], "approved_gate_job_ids": ["music"]},
        {"held_job_ids": ["scenario"], "completed_job_ids": ["scenario"]},
    ],
)
def test_invalid_or_inconsistent_evidence_fails_closed(kwargs):
    with pytest.raises(ValueError):
        derive_goal_job_chain_state(plan(), **kwargs)


def test_completed_job_cannot_skip_an_unapproved_dependency_gate():
    with pytest.raises(ValueError, match="incomplete or unapproved dependencies"):
        derive_goal_job_chain_state(
            plan(),
            completed_job_ids=["scenario", "music"],
            approved_gate_job_ids=[],
        )


def test_dependency_cycles_are_rejected():
    value = plan()
    value["stages"][0]["depends_on"] = ["game"]
    with pytest.raises(ValueError, match="dependency cycle"):
        derive_goal_job_chain_state(value)


def test_unknown_dependencies_are_rejected():
    value = plan()
    value["stages"][1]["depends_on"] = ["does-not-exist"]
    with pytest.raises(ValueError, match="unknown dependency"):
        derive_goal_job_chain_state(value)


def test_invalid_plan_schema_is_rejected():
    with pytest.raises(ValueError, match="schema_version"):
        derive_goal_job_chain_state({"schema_version": "wrong"})
