import pytest

import db
from agents.media.goal_job_chain_store import (
    GoalChainConflictError,
    create_or_resume_goal_chain,
    get_goal_chain,
    get_goal_chain_history,
    record_goal_chain_evidence,
)


def _plan():
    return {
        "schema_version": "audiovisual-to-game-sprint-plan.v1",
        "goal_id": "story-game-01",
        "objective": "Create an original audiovisual story and a small playable game.",
        "stages": [
            {"job_id": "scenario", "depends_on": [], "human_gate": "scenario_review"},
            {"job_id": "music", "depends_on": ["scenario"], "human_gate": "listening_review"},
            {"job_id": "visual", "depends_on": ["scenario"], "human_gate": "visual_review"},
            {"job_id": "sync", "depends_on": ["music", "visual"], "human_gate": None},
        ],
    }


@pytest.fixture
def chain_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "goal-chain.sqlite"))
    db.init_db()


def test_create_is_durable_and_repeated_request_is_idempotent(chain_db):
    first = create_or_resume_goal_chain("U-owner", _plan())
    resumed = create_or_resume_goal_chain("U-owner", _plan())

    assert first["version"] == 1
    assert resumed == first
    assert get_goal_chain("U-owner", "story-game-01") == first
    assert len(get_goal_chain_history("U-owner", "story-game-01")) == 1


def test_goal_id_cannot_be_reused_by_another_owner_or_changed_plan(chain_db):
    create_or_resume_goal_chain("U-owner", _plan())
    with pytest.raises(GoalChainConflictError):
        create_or_resume_goal_chain("U-other", _plan())

    changed = _plan()
    changed["objective"] = "different objective"
    with pytest.raises(GoalChainConflictError):
        create_or_resume_goal_chain("U-owner", changed)


def test_evidence_checkpoint_resumes_and_preserves_human_gate(chain_db):
    created = create_or_resume_goal_chain("U-owner", _plan())
    saved = record_goal_chain_evidence(
        "U-owner",
        "story-game-01",
        expected_version=created["version"],
        completed_job_ids=["scenario"],
        event_type="stage_completed",
    )

    assert saved["version"] == 2
    assert saved["state"]["state"]["scenario"] == "AWAITING_HUMAN_APPROVAL"
    assert saved["state"]["ready_job_ids"] == []
    assert get_goal_chain("U-owner", "story-game-01") == saved

    approved = record_goal_chain_evidence(
        "U-owner",
        "story-game-01",
        expected_version=saved["version"],
        approved_gate_job_ids=["scenario"],
        event_type="human_approved",
    )
    assert approved["version"] == 3
    assert approved["state"]["ready_job_ids"] == ["music", "visual"]


def test_identical_retry_is_idempotent_even_with_stale_version(chain_db):
    created = create_or_resume_goal_chain("U-owner", _plan())
    first = record_goal_chain_evidence(
        "U-owner", "story-game-01", expected_version=1,
        completed_job_ids=["scenario"], event_type="stage_completed",
    )
    retry = record_goal_chain_evidence(
        "U-owner", "story-game-01", expected_version=1,
        completed_job_ids=["scenario"], event_type="stage_completed",
    )
    assert retry == first
    assert len(get_goal_chain_history("U-owner", "story-game-01")) == 2


def test_conflicting_stale_update_is_rejected(chain_db):
    created = create_or_resume_goal_chain("U-owner", _plan())
    record_goal_chain_evidence(
        "U-owner", "story-game-01", expected_version=created["version"],
        completed_job_ids=["scenario"],
    )
    with pytest.raises(GoalChainConflictError):
        record_goal_chain_evidence(
            "U-owner", "story-game-01", expected_version=created["version"],
            held_job_ids=["visual"],
        )


def test_evidence_is_append_only_and_hold_propagates(chain_db):
    created = create_or_resume_goal_chain("U-owner", _plan())
    held = record_goal_chain_evidence(
        "U-owner", "story-game-01", expected_version=created["version"],
        held_job_ids=["visual"], event_type="hold_raised",
    )
    assert held["state"]["state"]["sync"] == "HOLD"
    with pytest.raises(ValueError, match="cannot be removed"):
        record_goal_chain_evidence(
            "U-owner", "story-game-01", expected_version=held["version"],
            held_job_ids=[],
        )


def test_owner_scope_and_unknown_chain_are_fail_closed(chain_db):
    create_or_resume_goal_chain("U-owner", _plan())
    assert get_goal_chain("U-other", "story-game-01") is None
    assert get_goal_chain_history("U-other", "story-game-01") == []
    with pytest.raises(KeyError):
        record_goal_chain_evidence(
            "U-other", "story-game-01", expected_version=1,
            completed_job_ids=["scenario"],
        )


def test_unsafe_or_invalid_evidence_is_rejected_without_version_change(chain_db):
    created = create_or_resume_goal_chain("U-owner", _plan())
    with pytest.raises(ValueError):
        record_goal_chain_evidence(
            "U-owner", "story-game-01", expected_version=1,
            approved_gate_job_ids=["music"],
        )
    assert get_goal_chain("U-owner", "story-game-01") == created
